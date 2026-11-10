"""Start locally: python start.py"""
import threading
import webbrowser
from app import app

if __name__ == '__main__':
    threading.Timer(1.4,lambda:webbrowser.open('http://127.0.0.1:8501')).start()
    app.run(host='127.0.0.1',port=8501,debug=False,use_reloader=False)
