"""Run the real packaged UI with isolated preferences and a bounded lifetime."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

def main():
    executable=Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        env=os.environ.copy()
        env.update(APPDATA=tmp,LOCALAPPDATA=tmp)
        # --smoke-test quits only after the application finishes constructing all controllers.
        subprocess.run([str(executable),'--smoke-test'],cwd=tmp,env=env,
                       timeout=45,check=True)
    print('Packaged application constructed its UI and shut down successfully.')

if __name__=='__main__':
    main()
