#!/home/jrising/projects/arachne.existencia.org/venv/bin/python
import sys, os
INTERP = os.path.join(os.environ['HOME'], 'projects', 'arachne.existencia.org', 'venv', 'bin', 'python3')
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)
sys.path.append(os.getcwd())

from app import app as application
