; Wave view for Program/Sounds -> 6 (Edit Sound), opened with Help.
; Evidence: notes/waveform_phase0.md, notes/waveform_engine.md.
; Pixel contract: emu/wave_ref.py (screen()).
;
; Hooks (mods/WAVE.args):
;   B060:0422 help_gate  field editor's Help test; on Edit Sound, return 'H'
;   B99A:085A page_key   Edit Sound key dispatch, plus 'H' -> view
; DS = 8010 (DGROUP) in both hooked routines and throughout.
; C convention inside: preserve SI, DI, BP, DS.
; cpu 186: the stock OS uses PUSH imm (68 iw at B000:0015).

bits 16
cpu 186
org 0

SND_SEG equ 0xA2AE              ; sound records at A2AE:4800 + idx*24h
SND_DIR equ 0x4800
BUF_W   equ 0x2400              ; Best st's read buffer A2AE:0000, words
FB      equ 0x1591              ; 8010:1591, 30 bytes x 64 rows, bit 7 = left
ROW     equ 30
COLS    equ 240
MID     equ 31                  ; zero line; rows 16..47 hold the wave
TOP     equ 16
BOT     equ 47
BUSY    equ 0x9757              ; transfer busy counter (INC/DEC round CF92)
MODE    equ 0xD7CB              ; 'L' = Program/Sounds
OPTION  equ 0xD7CA              ; 6 = Edit Sound

; ---------------------------------------------------------------- hooks

; Replaces `cmp byte [bp-1],48h / jnz 0459` in B060:035D.
help_gate:
        cmp byte [bp-1], 'H'
        jne .other
        cmp byte [MODE], 'L'
        jne .help
        cmp byte [OPTION], 6
        jne .help
        mov si, 'H'                     ; return the key like any other
        jmp 0xB060:0x06E2
.help:  jmp 0xB060:0x0428
.other: jmp 0xB060:0x0459

; Replaces `cmp ax,75h / jnz / jmp 0AF3 / jmp 1595` in the B99A:082E loop.
; AX = key (cbw). Page frame: [bp-1] key, [bp-2] list position,
; [bp-0BCh] sound index list, DI = -1 when there is no sound.
page_key:
        cmp ax, 0x75
        jne .h
        jmp 0xB99A:0x0AF3
.h:     cmp ax, 'H'
        jne .out
        mov byte [bp-1], 0
        cmp di, -1
        je .out
        mov al, [bp-2]
        cbw
        lea bx, [bp-0xBC]
        add bx, ax
        mov al, [ss:bx]
        push ax
        call view
        add sp, 2
        mov [bp-1], al
        or ah, ah
        jz .out
        push '6'                        ; reopen Edit Sound, as Best st does
        call 0xD6E0:0x0075
        add sp, 2
.out:   jmp 0xB99A:0x1595

; ---------------------------------------------------------------- view

; view(index): AL = key to hand back, AH = 1 to reopen Edit Sound.
view:
        push bp
        mov bp, sp
        push si
        push di
        mov al, [bp+4]
        cbw
        mov dx, 0x24
        imul dx
        add ax, SND_DIR
        mov [cs:rec], ax
        mov byte [cs:sel], 0
        call scan
        mov ax, [cs:len]                ; wheel step: one column, 1..FFFFh
        mov dx, [cs:len+2]
        mov cx, COLS
        cmp dx, cx
        jae .big                        ; quotient would overflow DIV
        div cx
        or ax, ax
        jnz .st
        inc ax
        jmp .st
.big:   mov ax, 0xFFFF
.st:    mov [cs:step], ax
        call draw
        call 0xC4C8:0x0F5F              ; graphics mode + blit 8010:1591
.key:   push 0
        call 0xBDE3:0x000E              ; next key after the global filter
        add sp, 2
        mov bx, ax
        mov ax, [cs:step]
        cmp bl, '+'
        je .move
        neg ax
        cmp bl, '-'
        je .move
        cmp bl, 'x'                     ; Soft Key 1 / Left: start
        je .s0
        cmp bl, '<'
        je .s0
        cmp bl, 'y'                     ; Soft Key 2 / Right: end
        je .s1
        cmp bl, '>'
        je .s1
        mov ah, 1                       ; Soft Key 4 / Help: back to Edit Sound
        mov al, 'L'
        cmp bl, 'u'
        je .exit
        cmp bl, 'H'
        je .exit
        xor ah, ah                      ; mode keys: leave, the OS switches
        mov al, bl
        mov di, modes
.m:     mov bh, [cs:di]
        or bh, bh
        jz .key                         ; anything else, including 'h': ignore
        inc di
        cmp bh, bl
        je .exit
        jmp .m
.s0:    mov byte [cs:sel], 0
        jmp .redraw
.s1:    mov byte [cs:sel], 1
        jmp .redraw
.move:  call move
.redraw:
        call draw
        call 0xC4C8:0x0F0D              ; blit
        jmp .key
.exit:  push ax
        call 0xC4C8:0x0409              ; clear, text mode, INT 43 AX=1
        pop ax
        pop di
        pop si
        pop bp
        ret

; Move the selected point by AX (signed) and clamp: 0 <= start <= end <= len.
move:
        mov cx, SND_SEG
        mov es, cx
        mov si, [cs:rec]
        cwd
        mov bx, 0x14                    ; start: [0, end]
        cmp byte [cs:sel], 0
        je .add
        mov bx, 0x18                    ; end: [start, len]
.add:   add ax, [es:si+bx]
        adc dx, [es:si+bx+2]
        js .lo                          ; below zero
        cmp byte [cs:sel], 0
        jne .end
        cmp dx, [es:si+0x1A]            ; start > end ?
        jl .ok
        jg .hiE
        cmp ax, [es:si+0x18]
        jbe .ok
.hiE:   mov ax, [es:si+0x18]
        mov dx, [es:si+0x1A]
        jmp .ok
.end:   cmp dx, [cs:len+2]              ; end > len ?
        jl .loE
        jg .hiL
        cmp ax, [cs:len]
        jbe .loE
.hiL:   mov ax, [cs:len]
        mov dx, [cs:len+2]
.loE:   cmp dx, [es:si+0x16]            ; end < start ?
        jg .ok
        jl .loS
        cmp ax, [es:si+0x14]
        jae .ok
.loS:   mov ax, [es:si+0x14]
        mov dx, [es:si+0x16]
        jmp .ok
.lo:    xor ax, ax
        xor dx, dx
        cmp byte [cs:sel], 0
        jne .loS
.ok:    mov [es:si+bx], ax
        mov [es:si+bx+2], dx
        ret

; ---------------------------------------------------------------- scan

; DX:AX = CX * len / 240 (CX <= 240, len < 2^24).
bound:
        mov ax, [cs:len+2]
        mul cx
        mov bx, ax
        mov ax, [cs:len]
        mul cx
        add dx, bx
        mov bx, ax
        mov ax, dx
        xor dx, dx
        mov cx, COLS
        div cx
        xchg ax, bx
        div cx
        mov dx, bx
        ret

; Read min(BUF_W, len - cur) words from wave + cur into A2AE:0000.
fill:
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        sub ax, [cs:cur]
        sbb dx, [cs:cur+2]
        jnz .full
        cmp ax, BUF_W
        jbe .n
.full:  mov ax, BUF_W
.n:     mov bx, [cs:cur]
        mov cx, [cs:cur+2]
        mov [cs:bstart], bx
        mov [cs:bstart+2], cx
        add bx, ax
        adc cx, 0
        mov [cs:bend], bx
        mov [cs:bend+2], cx
        mov bx, [cs:wave]
        mov cx, [cs:wave+2]
        add bx, [cs:cur]
        adc cx, [cs:cur+2]
        inc byte [BUSY]
        push 1                          ; read
        push 0
        push ax                         ; count
        push cx
        push bx                         ; wave word address
        push SND_SEG
        push 0
        call 0xCF92:0x000C
        add sp, 14
        dec byte [BUSY]
        ret

; Column c covers samples [bound(c), max(bound(c+1), bound(c)+1)).
scan:
        mov ax, SND_SEG
        mov es, ax
        mov si, [cs:rec]
        mov ax, [es:si+0x1C]
        mov dx, [es:si+0x1E]
        mov [cs:len], ax
        mov [cs:len+2], dx
        mov ax, [es:si+0x20]
        mov dx, [es:si+0x22]
        mov [cs:wave], ax
        mov [cs:wave+2], dx
        xor ax, ax
        mov [cs:bend], ax               ; empty buffer: first sample refills
        mov [cs:bend+2], ax
        mov [cs:col], ax
.col:   mov cx, [cs:col]
        call bound
        mov [cs:cur], ax
        mov [cs:cur+2], dx
        mov cx, [cs:col]
        inc cx
        call bound
        cmp dx, [cs:cur+2]
        ja .hi
        jb .one
        cmp ax, [cs:cur]
        ja .hi
.one:   mov ax, [cs:cur]
        mov dx, [cs:cur+2]
        add ax, 1
        adc dx, 0
.hi:    mov [cs:hi], ax
        mov [cs:hi+2], dx
        mov word [cs:vmax], -32768
        mov word [cs:vmin], 32767
.run:   mov ax, [cs:cur]
        mov dx, [cs:cur+2]
        cmp dx, [cs:hi+2]
        jb .in
        ja .done
        cmp ax, [cs:hi]
        jae .done
.in:    cmp dx, [cs:bend+2]
        jb .have
        ja .refill
        cmp ax, [cs:bend]
        jb .have
.refill:
        call fill
        mov ax, [cs:cur]
        mov dx, [cs:cur+2]
.have:  mov cx, [cs:hi]                 ; k = min(hi, bend) - cur (<= BUF_W)
        mov bx, [cs:hi+2]
        cmp bx, [cs:bend+2]
        jb .k
        ja .kb
        cmp cx, [cs:bend]
        jbe .k
.kb:    mov cx, [cs:bend]
.k:     sub cx, ax
        add ax, cx                      ; cur += k
        adc dx, 0
        mov [cs:cur], ax
        mov [cs:cur+2], dx
        sub ax, cx                      ; SI = (old cur - bstart) * 2
        sub ax, [cs:bstart]
        shl ax, 1
        mov si, ax
        mov ax, SND_SEG
        mov es, ax
        mov bx, [cs:vmax]
        mov dx, [cs:vmin]
.s:     mov ax, [es:si]
        add si, 2
        cmp ax, bx
        jle .nmax
        mov bx, ax
.nmax:  cmp ax, dx
        jge .nmin
        mov dx, ax
.nmin:  loop .s
        mov [cs:vmax], bx
        mov [cs:vmin], dx
        jmp .run
.done:  mov bx, [cs:col]
        mov cl, 11
        mov ax, [cs:vmax]
        sar ax, cl
        neg ax
        add ax, MID
        mov [cs:tops+bx], al
        mov ax, [cs:vmin]
        sar ax, cl
        neg ax
        add ax, MID
        mov [cs:bots+bx], al
        inc bx
        mov [cs:col], bx
        cmp bx, COLS
        jb .col
        ret

; ---------------------------------------------------------------- draw

; AX = column holding sample position DX:AX: the largest c < 240 with
; bound(c) <= position.
column:
        mov [cs:pos], ax
        mov [cs:pos+2], dx
        xor di, di
.c:     mov cx, di
        inc cx
        cmp cx, COLS
        jae .r
        call bound
        cmp dx, [cs:pos+2]
        ja .r
        jb .n
        cmp ax, [cs:pos]
        ja .r
.n:     inc di
        jmp .c
.r:     mov ax, di
        ret

; XOR the pixels x = BX .. BX+CX-1 on rows AX .. AX+DX-1.
invert:
.y:     push bx
        push cx
.x:     push cx
        call pixel
        xor [di], cl
        pop cx
        inc bx
        loop .x
        pop cx
        pop bx
        inc ax
        dec dx
        jnz .y
        ret

; DI = framebuffer byte, CL = bit mask of pixel (BX, AX). Keeps AX, BX, DX.
pixel:
        push ax
        push dx
        mov dl, ROW
        mul dl
        mov di, bx
        shr di, 1
        shr di, 1
        shr di, 1
        add di, ax
        add di, FB
        mov cl, bl
        and cl, 7
        mov al, 0x80
        shr al, cl
        mov cl, al
        pop dx
        pop ax
        ret

; Draw the zero-terminated string at CS:SI with its first cell at text
; row AX, column BX (6 x 8 cells, glyph in the top 7 rows).
text:
        shl ax, 1
        shl ax, 1
        shl ax, 1
        mov dx, bx
        shl bx, 1
        add bx, dx
        shl bx, 1
.ch:    mov dl, [cs:si]
        or dl, dl
        jz .end
        inc si
        push si
        sub dl, 0x20
        xor dh, dh
        mov si, dx
        shl si, 1
        shl si, 1
        shl si, 1
        sub si, dx                      ; 7 bytes per glyph
        add si, font
        push ax
        mov dh, 7
.r:     mov dl, [cs:si]
        inc si
        push bx
        mov ch, 5
.b:     test dl, 0x10
        jz .nb
        push dx
        call pixel
        or [di], cl
        pop dx
.nb:    shl dl, 1
        inc bx
        dec ch
        jnz .b
        pop bx
        inc ax
        dec dh
        jnz .r
        pop ax
        add bx, 6
        pop si
        jmp .ch
.end:   ret

; 10-character "sss.mmm.ss" of DX:AX frames at CS:DI (the OS field units:
; frames = s*44100 + ms*441/10 + samples, B99A:2619).
fmt:
        mov cx, 44100
        div cx
        mov [cs:rem], dx
        mov cx, 3
        call digits
        mov byte [cs:di], '.'
        inc di
        mov ax, [cs:rem]
        mov cx, 10
        mul cx
        mov cx, 441
        div cx
        push ax
        mov cx, 3
        call digits
        mov byte [cs:di], '.'
        inc di
        pop ax
        mov cx, 441
        mul cx
        mov cx, 10
        div cx
        neg ax
        add ax, [cs:rem]
        mov cx, 2
        call digits
        mov byte [cs:di], 0
        ret

; CX decimal digits of AX at CS:DI, zero padded; DI advances.
digits:
        add di, cx
        push di
        mov bx, 10
.d:     xor dx, dx
        div bx
        add dl, '0'
        dec di
        mov [cs:di], dl
        loop .d
        pop di
        ret

; Frame, wave, start..end inversion, text, selected value inverted.
draw:
        push ds
        pop es
        mov di, FB
        mov cx, ROW * 64 / 2
        xor ax, ax
        rep stosw
        xor bx, bx
.x:     mov al, [cs:tops+bx]
        xor ah, ah
        push bx
        call pixel
        pop bx
        mov al, cl
        mov cl, [cs:bots+bx]
        sub cl, [cs:tops+bx]
        inc cl
        xor ch, ch
.y:     or [di], al
        add di, ROW
        loop .y
        inc bx
        cmp bx, COLS
        jb .x
        mov ax, SND_SEG
        mov es, ax
        mov si, [cs:rec]
        mov ax, [es:si+0x14]
        mov dx, [es:si+0x16]
        call column
        mov [cs:xs], ax
        mov ax, SND_SEG
        mov es, ax
        mov ax, [es:si+0x18]
        mov dx, [es:si+0x1A]
        call column
        mov cx, ax
        mov bx, [cs:xs]
        sub cx, bx
        inc cx
        mov ax, TOP
        mov dx, BOT - TOP + 1
        call invert
        mov ax, SND_SEG                 ; name: 16 characters at +00
        mov es, ax
        mov si, [cs:rec]
        xor bx, bx
.nm:    mov al, [es:si+bx]
        mov [cs:name+bx], al
        inc bx
        cmp bx, 16
        jb .nm
        mov byte [cs:name+16], 0
        xor ax, ax
        xor bx, bx
        mov si, s_title
        call text
        xor ax, ax
        mov bx, 9
        mov si, name
        call text
        mov ax, 1
        xor bx, bx
        mov si, s_start
        call text
        mov ax, 1
        mov bx, 20
        mov si, s_end
        call text
        mov ax, 6
        xor bx, bx
        mov si, s_len
        call text
        mov ax, 7
        xor bx, bx
        mov si, s_keys
        call text
        mov bx, 0x14
        mov cx, 6
        call value
        mov bx, 0x18
        mov cx, 24
        call value
        mov di, num
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        call fmt
        mov ax, 6
        mov bx, 7
        mov si, num
        call text
        mov bx, 6                       ; selected value, inverted
        cmp byte [cs:sel], 0
        je .sv
        mov bx, 24
.sv:    mov ax, bx
        shl bx, 1
        add bx, ax
        shl bx, 1
        mov cx, 60
        mov ax, 8
        mov dx, 8
        call invert
        ret

; Text row 1, column CX: the record dword at +BX in sss.mmm.ss.
value:
        push cx
        mov ax, SND_SEG
        mov es, ax
        mov si, [cs:rec]
        mov ax, [es:si+bx]
        mov dx, [es:si+bx+2]
        mov di, num
        call fmt
        pop bx
        mov ax, 1
        mov si, num
        call text
        ret

s_title: db "Edit Snd:", 0
s_start: db "Start:", 0
s_end:   db "End:", 0
s_len:   db "Length:", 0
s_keys:  db "<Start>   <End>                   <Exit>", 0
modes:   db "LMFJGUSlsOK", 0            ; mode keys (D547:0006 codes)

%include "wave_font.inc"

align 2
rec:    dw 0
col:    dw 0
xs:     dw 0
step:   dw 0
rem:    dw 0
sel:    db 0
align 2
len:    dd 0
wave:   dd 0
cur:    dd 0
hi:     dd 0
pos:    dd 0
bstart: dd 0
bend:   dd 0
vmax:   dw 0
vmin:   dw 0
tops:   times COLS db 0
bots:   times COLS db 0
name:   times 17 db 0
num:    times 11 db 0
