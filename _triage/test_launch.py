import subprocess, time
EXE_R = r'F:\Projects\SuperMarioWorldRecomp\build\bin-x64-Release\smw.exe'
EXE_O = r'F:\Projects\SuperMarioWorldRecomp\build\bin-x64-Oracle\smw.exe'
for label, exe in [('Release', EXE_R), ('Oracle', EXE_O)]:
    print(f'--- trying {label} ({exe}) ---')
    try:
        p = subprocess.Popen([exe], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             cwd=r'F:\Projects\SuperMarioWorldRecomp')
        time.sleep(1.5)
        alive = p.poll() is None
        print(f'  alive: {alive}, returncode: {p.returncode}')
        p.terminate()
        try: p.wait(timeout=3)
        except subprocess.TimeoutExpired: p.kill()
    except OSError as e:
        print(f'  OSError: {e}')
