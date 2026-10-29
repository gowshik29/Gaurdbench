import json, shutil, sys, urllib.request, urllib.error
def main():
    print("Python:", sys.version.split()[0])
    print("Git:", "found" if shutil.which("git") else "NOT FOUND")
    print("Ollama CLI:", "found" if shutil.which("ollama") else "NOT FOUND")
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data=json.loads(r.read().decode())
        names=[m.get("name","") for m in data.get("models",[])]
        print("Ollama API: reachable")
        print("Models:", ", ".join(names) if names else "(none)")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print("Ollama API: not reachable:", e)
        print("Open the Ollama desktop app and retry.")
if __name__=="__main__": main()
