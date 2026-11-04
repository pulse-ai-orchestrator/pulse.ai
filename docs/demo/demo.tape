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

Hide
Type "bash docs/demo/prepare.sh && export HOME=/tmp/pulse-demo/home PATH=/tmp/pulse-demo/bin:$PATH PS1='$ ' && cd /tmp/pulse-demo/calculadora && pulse daemon start >/dev/null && clear"
Enter
Sleep 12s
Show

Type "pulse"
Sleep 300ms
Enter
Sleep 2500ms

Enter
Sleep 1500ms
Down
Sleep 1200ms
Enter
Sleep 800ms

Type "media() quebra com lista vazia"
Sleep 600ms
Enter
Sleep 7s

Enter
Sleep 6s

Up
Sleep 800ms
Type "a"
Sleep 4s

Hide
Type "q"
Sleep 1s
Type "q"
Sleep 1s
Type "pulse daemon stop >/dev/null"
Enter
Sleep 2s
