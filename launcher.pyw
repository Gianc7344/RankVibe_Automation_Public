import os
import socket
import time
import subprocess
import webbrowser

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def get_chrome_path():
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def get_edge_path():
    paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def main():
    port = 5000
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if not is_port_in_use(port):
        python_exec = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')
        app_script = os.path.join(base_dir, 'app.py')
        
        if not os.path.exists(python_exec):
            # Fallback if venv is missing
            python_exec = "python"
            
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        subprocess.Popen(
            [python_exec, app_script],
            cwd=base_dir,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )
        
        # Wait up to 5 seconds for server to start
        for _ in range(20):
            if is_port_in_use(port):
                time.sleep(0.5)
                break
            time.sleep(0.25)
            
    url = f"http://localhost:{port}"
    chrome_path = get_chrome_path()
    edge_path = get_edge_path()
    
    if chrome_path:
        subprocess.Popen([chrome_path, f"--app={url}"])
    elif edge_path:
        subprocess.Popen([edge_path, f"--app={url}"])
    else:
        webbrowser.open(url)

if __name__ == "__main__":
    main()
