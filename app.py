"""Flask API and HTML UI for Smart Shipment Distribution. Run: python start.py"""
from flask import Flask, jsonify, render_template, request
from database import setup, state, book, reschedule, delay, delay_from, deliver, rate, advance, reset, save_customer_note, arrived, LogicError

app = Flask(__name__)
setup()

@app.get('/')
def index(): return render_template('index.html')

@app.get('/api/state')
def get_state(): return jsonify(state())

@app.post('/api/<action>')
def action_api(action):
    data=request.get_json(silent=True) or {}
    try:
        if action=='book': book(int(data['id']),int(data['minute']))
        elif action=='reschedule': reschedule(int(data['id']), int(data['minute']))
        elif action=='delay': delay(int(data['driver_id']),int(data['minutes']))
        elif action=='delay_from': delay_from(int(data['driver_id']),int(data['id']),int(data.get('minutes',15)))
        elif action=='arrived': arrived(int(data['driver_id']),int(data['id']))
        elif action=='deliver': deliver(int(data['driver_id']),int(data['id']))
        elif action=='rate': rate(int(data['id']),int(data['rating']))
        elif action=='note': save_customer_note(int(data['id']),data['note'])
        elif action=='advance': advance()
        elif action=='reset': reset()
        else: return jsonify(error='الإجراء غير موجود.'),404
        return jsonify(ok=True)
    except (LogicError,ValueError,TypeError,KeyError) as exc:
        return jsonify(error=str(exc)),400

if __name__=='__main__': app.run(host='127.0.0.1',port=8501,debug=False)
