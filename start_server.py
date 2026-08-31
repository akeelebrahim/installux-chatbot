import subprocess
import sys
import os

os.chdir('C:\\Users\\PC\\Documents\\Default Project\\Installux-ChatBot')
proc = subprocess.Popen([sys.executable, 'app.py'],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
print('Server PID:', proc.pid)
print('Starting Installux-ChatBot on port 8509...')