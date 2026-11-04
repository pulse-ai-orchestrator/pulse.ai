Output "docs/demo/demo.gif"

Require bash
Require git
Require nc

Set Shell "bash"
Set FontSize 16
Set Width 1280
Set Height 760
Set Padding 16
Set Framerate 24
Set TypingSpeed 45ms
Set Theme { "name": "Pulse", "black": "#000000", "red": "#FF5555", "green": "#A2D729", "yellow": "#E6C229", "blue": "#5FA8D3", "magenta": "#C792EA", "cyan": "#5FD7D7", "white": "#E0E0E0", "brightBlack": "#555555", "brightRed": "#FF6E6E", "brightGreen": "#B8F040", "brightYellow": "#F0D060", "brightBlue": "#7FC1E8", "brightMagenta": "#D7A8F0", "brightCyan": "#7FE8E8", "brightWhite": "#FFFFFF", "background": "#000000", "foreground": "#E0E0E0", "selection": "#333333", "cursor": "#A2D729" }

Env TERM "xterm-256color"
Env COLORTERM "truecolor"

Hide
Type "unset NO_COLOR FORCE_COLOR && bash docs/demo/prepare.sh && export HOME=/tmp/pulse-demo/home PATH=/tmp/pulse-demo/bin:$PATH PS1='$ ' && cd /tmp/pulse-demo/calculadora && pulse daemon start >/dev/null && clear"
Enter
Sleep 12s
Show

Type "pulse"
Sleep 300ms
Enter
Sleep 2200ms

Enter
Sleep 1300ms
Down
Sleep 1200ms
Enter
Sleep 700ms

Type "media() quebra com lista vazia"
Sleep 500ms
Enter
Sleep 7s

Enter
Sleep 8s

Type "a"
Sleep 2s
Type "["
Sleep 2500ms
Type "["
Sleep 3s

Hide
Type "q"
Sleep 1s
Type "q"
Sleep 1s
Type "pulse daemon stop >/dev/null"
Enter
Sleep 2s
