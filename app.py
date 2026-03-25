import os, json, random, string, time
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
DATA_FILE = 'data.json'

# ── Helpers ────────────────────────────────────────────────────

def load():
    if not os.path.exists(DATA_FILE):
        return {'devices': {}, 'codes': {}}
    with open(DATA_FILE) as f:
        return json.load(f)

def save(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def gen_code():
    return ''.join(random.choices(string.digits, k=6))

# ── Routes ─────────────────────────────────────────────────────

@app.route('/check')
def check():
    hwid = request.args.get('hwid', '')
    if not hwid:
        return jsonify({'ok': False, 'reason': 'no_hwid'})
    data = load()
    if hwid in data['devices'] and data['devices'][hwid].get('authorised'):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'reason': 'not_linked'})

@app.route('/generate-code')
def generate_code():
    hwid = request.args.get('hwid', '')
    if not hwid:
        return jsonify({'error': 'no_hwid'}), 400
    data = load()
    # Reuse unexpired code if exists
    for code, entry in data['codes'].items():
        if entry['hwid'] == hwid and entry['expires'] > time.time():
            return jsonify({'code': code})
    # Generate new code
    code = gen_code()
    while code in data['codes']:
        code = gen_code()
    data['codes'][code] = {
        'hwid': hwid,
        'expires': time.time() + 600  # 10 minutes
    }
    save(data)
    return jsonify({'code': code})

@app.route('/link')
def link_page():
    code = request.args.get('code', '')
    html = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { background:#0a0010; color:#00ff59; font-family:monospace; display:flex;
         flex-direction:column; align-items:center; justify-content:center;
         min-height:100vh; margin:0; padding:20px; box-sizing:border-box; }
  h1 { color:#7700ff; font-size:2em; margin-bottom:10px; }
  .code { font-size:3em; letter-spacing:8px; color:#fff; background:#1a0030;
          padding:20px 30px; border-radius:12px; border:2px solid #7700ff;
          margin:20px 0; }
  .step { background:#0d001a; border:1px solid #330066; border-radius:8px;
          padding:15px; margin:10px 0; width:100%; max-width:400px; }
  .step b { color:#7700ff; }
  .cmd { background:#000; color:#00ff59; padding:8px 12px; border-radius:6px;
         font-size:1.1em; display:inline-block; margin:4px 0; }
</style>
</head>
<body>
  <h1>N5 Menu Auth</h1>
  <p>Your device code:</p>
  <div class="code">{{ code }}</div>
  <div class="step"><b>Step 1</b><br>Join the Discord server</div>
  <div class="step"><b>Step 2</b><br>Run this command in any channel:<br>
    <span class="cmd">/link-device {{ code }}</span>
  </div>
  <div class="step"><b>Step 3</b><br>Relaunch the game — menu will load automatically</div>
  <p style="color:#666;font-size:0.8em">Code expires in 10 minutes</p>
</body>
</html>
""".replace('{{ code }}', code if code else 'INVALID')
    return html

@app.route('/bot-link', methods=['POST'])
def bot_link():
    """Called by the Discord bot to link a device"""
    token = request.headers.get('X-Bot-Token', '')
    if token != os.environ.get('BOT_TOKEN', ''):
        return jsonify({'error': 'unauthorized'}), 403
    body = request.json
    code  = body.get('code', '')
    discord_id = body.get('discord_id', '')
    data = load()
    # Validate code
    entry = data['codes'].get(code)
    if not entry:
        return jsonify({'ok': False, 'reason': 'invalid_code'})
    if entry['expires'] < time.time():
        del data['codes'][code]
        save(data)
        return jsonify({'ok': False, 'reason': 'expired'})
    hwid = entry['hwid']
    # Check this discord user doesn't already have a linked device
    for h, dev in data['devices'].items():
        if dev.get('discord_id') == discord_id and h != hwid:
            return jsonify({'ok': False, 'reason': 'already_linked', 'hwid': h})
    # Link it
    data['devices'][hwid] = {'discord_id': discord_id, 'authorised': True, 'linked_at': time.time()}
    del data['codes'][code]
    save(data)
    return jsonify({'ok': True, 'hwid': hwid})

@app.route('/bot-change', methods=['POST'])
def bot_change():
    """Called by the Discord bot to change a device"""
    token = request.headers.get('X-Bot-Token', '')
    if token != os.environ.get('BOT_TOKEN', ''):
        return jsonify({'error': 'unauthorized'}), 403
    body = request.json
    discord_id = body.get('discord_id', '')
    new_hwid   = body.get('new_hwid', '')
    data = load()
    # Find and remove old device for this discord user
    old_hwid = None
    for h, dev in list(data['devices'].items()):
        if dev.get('discord_id') == discord_id:
            old_hwid = h
            del data['devices'][h]
            break
    if not old_hwid:
        return jsonify({'ok': False, 'reason': 'no_linked_device'})
    # Link new device
    data['devices'][new_hwid] = {'discord_id': discord_id, 'authorised': True, 'linked_at': time.time()}
    save(data)
    return jsonify({'ok': True, 'old_hwid': old_hwid, 'new_hwid': new_hwid})

@app.route('/bot-unlink', methods=['POST'])
def bot_unlink():
    """Admin: revoke a device"""
    token = request.headers.get('X-Bot-Token', '')
    if token != os.environ.get('BOT_TOKEN', ''):
        return jsonify({'error': 'unauthorized'}), 403
    body = request.json
    hwid = body.get('hwid', '')
    data = load()
    if hwid in data['devices']:
        del data['devices'][hwid]
        save(data)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'reason': 'not_found'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
