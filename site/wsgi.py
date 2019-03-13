import os, sys

VENV_DIR = '/opt/Envs/debijenkorf/lib/python3.6/site-packages'
WSGI_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(WSGI_DIR)
sys.path.append(WSGI_DIR)
sys.path.append(APP_DIR)

from main import Flask, WebApp

application = Flask(__name__, template_folder='../templates')
WebApp(application)
