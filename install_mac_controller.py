"""Install the paired Mac controller at login. Does not start courier or WhatsApp jobs."""
import os,plistlib,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
python=root/'.venv/bin/python'
station=root/'instance/mac-station/PRINTPRO3D-station'
if not python.exists() or not (station/'settings.json').exists():raise SystemExit('Set up and pair the Mac station first.')
folder=Path.home()/'Library/LaunchAgents';folder.mkdir(parents=True,exist_ok=True)
path=folder/'lk.printpro3d.station-controller.plist'
job={'Label':'lk.printpro3d.station-controller','ProgramArguments':['/usr/bin/open','-a','Terminal',str(root/'start_mac_controller.command')],'RunAtLoad':True,'StandardOutPath':str(station/'controller-launch.log'),'StandardErrorPath':str(station/'controller-launch.log')}
path.write_bytes(plistlib.dumps(job));path.chmod(0o600)
domain='gui/'+str(os.getuid())
subprocess.run(['launchctl','bootout',domain+'/lk.printpro3d.station-controller'],capture_output=True)
subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
print('Home PC controller installed. It starts at Mac login. Use the buttons on OMS Home PC.')
