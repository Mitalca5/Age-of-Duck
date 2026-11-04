"""Names shared by the process watcher and native window detection."""
GAME_EXECUTABLES = frozenset(("aoe2de_s.exe", "aoe2de.exe"))

def is_game_process(name):
    return isinstance(name, str) and name.lower() in GAME_EXECUTABLES
