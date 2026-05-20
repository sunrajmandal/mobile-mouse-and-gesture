Set oWS = WScript.CreateObject("WScript.Shell")
oWS.CurrentDirectory = "C:\Users\ASUS\.gemini\antigravity\scratch\ai_mouse_control"
oWS.Run "cmd /c ""C:\Program Files\PyManager\python.exe"" server.py", 0, False
