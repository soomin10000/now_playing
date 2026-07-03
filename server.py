#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import dbus
    _DBUS_OK = True
except ImportError:
    _DBUS_OK = False

PORT = 8195
MAX_ART_BYTES = 8 * 1024 * 1024

_ART_DOMAINS = {
    'lh3.googleusercontent.com', 'lh4.googleusercontent.com',
    'lh5.googleusercontent.com', 'lh6.googleusercontent.com',
    'yt3.ggpht.com', 'i.ytimg.com',
    'i1.ytimg.com', 'i2.ytimg.com', 'i3.ytimg.com', 'i4.ytimg.com',
    'music.youtube.com',
}


def get_now_playing():
    if not _DBUS_OK:
        return {'playing': False, 'error': 'dbus not available'}
    try:
        bus = dbus.SessionBus()
        for name in bus.list_names():
            if not str(name).startswith('org.mpris.MediaPlayer2.'):
                continue
            try:
                props = dbus.Interface(
                    bus.get_object(str(name), '/org/mpris/MediaPlayer2'),
                    'org.freedesktop.DBus.Properties',
                )
                status = str(props.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus'))
                meta = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata')
            except Exception:
                continue

            artists = meta.get('xesam:artist', [])
            artist = ', '.join(str(a) for a in artists) if artists else ''
            return {
                'playing': status == 'Playing',
                'paused': status == 'Paused',
                'title': str(meta.get('xesam:title', '')),
                'artist': artist,
                'album': str(meta.get('xesam:album', '')),
                'art_url': str(meta.get('mpris:artUrl', '')),
                'player': str(name).split('.')[-1],
            }
        return {'playing': False}
    except Exception as e:
        return {'playing': False, 'error': str(e)}


PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Now Playing</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
      background: #111;
      color: #fff;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      position: relative;
    }

    #bg {
      position: fixed;
      inset: -60px;
      background-size: cover;
      background-position: center;
      filter: blur(50px) brightness(0.4) saturate(1.4);
      transition: background-image 1s ease;
      z-index: 0;
    }

    #card {
      position: relative;
      z-index: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 28px;
      padding: 48px 40px;
      max-width: 420px;
      width: 100%;
      text-align: center;
    }

    #art-wrap {
      width: 280px;
      height: 280px;
      flex-shrink: 0;
      border-radius: 8px;
      overflow: hidden;
      background: #222;
      box-shadow: 0 20px 60px rgba(0,0,0,0.6);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: opacity 0.4s;
    }

    #art {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    #no-art {
      font-size: 80px;
      line-height: 1;
      opacity: 0.3;
    }

    #info {
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: 100%;
      transition: opacity 0.4s;
    }

    #title {
      font-size: 1.6rem;
      font-weight: 700;
      line-height: 1.2;
      letter-spacing: -0.3px;
      color: #fff;
    }

    #artist {
      font-size: 1rem;
      color: #bbb;
      font-weight: 500;
    }

    #album {
      font-size: 0.85rem;
      color: #777;
      font-style: italic;
    }

    #status {
      font-size: 0.75rem;
      color: #555;
      letter-spacing: 1px;
      text-transform: uppercase;
      margin-top: 4px;
    }

    #idle {
      display: none;
      flex-direction: column;
      align-items: center;
      gap: 16px;
      opacity: 0.4;
    }

    #idle .icon { font-size: 64px; }
    #idle p { font-size: 1rem; color: #888; }

    body.idle #card > :not(#idle) { display: none; }
    body.idle #idle { display: flex; }
    body.idle #bg { background-image: none !important; }

    @media (max-width: 480px) {
      #art-wrap { width: 220px; height: 220px; }
      #title { font-size: 1.3rem; }
      #card { padding: 32px 20px; }
    }
  </style>
</head>
<body class="idle">
  <div id="bg"></div>
  <div id="card">
    <div id="art-wrap">
      <img id="art" src="" alt="" style="display:none">
      <span id="no-art">♪</span>
    </div>
    <div id="info">
      <div id="title"></div>
      <div id="artist"></div>
      <div id="album"></div>
      <div id="status"></div>
    </div>
    <div id="idle">
      <span class="icon">🎵</span>
      <p>Nothing playing</p>
    </div>
  </div>
<script>
let _lastTitle = null;
let _lastArt = null;

async function poll() {
  try {
    const r = await fetch('/api/now-playing');
    const d = await r.json();

    if (!d.playing && !d.paused) {
      document.body.className = 'idle';
      return;
    }

    document.body.className = '';

    if (d.title !== _lastTitle) {
      document.getElementById('title').textContent = d.title || '(Unknown)';
      document.getElementById('artist').textContent = d.artist || '';
      document.getElementById('album').textContent = d.album || '';
      _lastTitle = d.title;
    }

    document.getElementById('status').textContent = d.paused ? '⏸ Paused' : '▶ Playing';

    if (d.art_url && d.art_url !== _lastArt) {
      const artSrc = '/api/art?url=' + encodeURIComponent(d.art_url);
      const bg = document.getElementById('bg');
      const img = document.getElementById('art');
      const noArt = document.getElementById('no-art');
      bg.style.backgroundImage = `url(${artSrc})`;
      img.src = artSrc;
      img.style.display = 'block';
      noArt.style.display = 'none';
      _lastArt = d.art_url;
    } else if (!d.art_url) {
      document.getElementById('art').style.display = 'none';
      document.getElementById('no-art').style.display = '';
      document.getElementById('bg').style.backgroundImage = 'none';
      _lastArt = null;
    }
  } catch (e) {
    // server unreachable — keep showing last state
  }
}

poll();
setInterval(poll, 3000);
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, content_type, body):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, 'application/json', json.dumps(data))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == '/':
            self._send(200, 'text/html; charset=utf-8', PAGE)

        elif path == '/api/now-playing':
            self._json(get_now_playing())

        elif path == '/api/art':
            url = qs.get('url', [''])[0]
            try:
                parsed_url = urllib.parse.urlparse(url)
                if parsed_url.scheme not in ('http', 'https') or parsed_url.netloc not in _ART_DOMAINS:
                    self._send(400, 'text/plain', 'url not allowed')
                    return
            except Exception:
                self._send(400, 'text/plain', 'bad url')
                return
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    ct = resp.headers.get('Content-Type', 'image/jpeg')
                    data = resp.read(MAX_ART_BYTES + 1)
                if len(data) > MAX_ART_BYTES:
                    self._send(502, 'text/plain', 'image too large')
                    return
                # Don't let an upstream response dictate a non-image Content-Type that
                # the browser could render as HTML/JS on our origin.
                if not ct.lower().startswith('image/'):
                    ct = 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._send(502, 'text/plain', str(e))

        else:
            self._send(404, 'text/plain', 'not found')


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f'Now Playing on http://0.0.0.0:{PORT}')
    server.serve_forever()
