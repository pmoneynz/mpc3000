; Cave demo: the version screen's third line comes from code and data in the
; code cave. Hooked from B000:0038 (file 0x30038), which pushed DS:1110 for
; the centred-line helper B202:000E. Entry and exit state match that call.
; cpu 186: the stock OS itself uses PUSH imm (68 iw at B000:0015).

bits 16
cpu 186
org 0

cave_line:
        push cs
        push msg
        call 0xB202:0x000E
        add sp, 4
        retf

msg:    db "Cave code ran", 0
