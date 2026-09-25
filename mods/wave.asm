; Wave view engine: scan a sound into a 240-column min/max cache, render it
; into the Mixer framebuffer 8010:1591 and show it in LCD graphics mode.
; Evidence: notes/waveform_phase0.md. Pixel contract: emu/wave_ref.py.
;
; Entry wave_test replaces Best st's `push cs / call 28F9` at B99A:08CF
; (file 0x3A26F) and keeps its contract: args [bp+6] sound index (byte),
; [bp+8] far pointer to a dword the caller then stores as soft start (+14).
; Returns AL = the key that closed the view ('L' re-enters Edit Sound).
; C convention: preserve SI, DI, BP, DS (DS = 8010 throughout).
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

wave_test:
        push bp
        mov bp, sp
        push si
        push di
        mov al, [bp+6]
        cbw
        mov dx, 0x24
        imul dx
        add ax, SND_DIR
        mov [cs:rec], ax
        mov si, ax
        mov ax, SND_SEG
        mov es, ax
        mov ax, [es:si+0x14]            ; hand soft start back unchanged
        mov dx, [es:si+0x16]
        les bx, [bp+8]
        mov [es:bx], ax
        mov [es:bx+2], dx
        call scan
        call render
        call 0xC4C8:0x0F5F              ; graphics mode + blit 8010:1591
.key:   push 0
        call 0xBDE3:0x000E              ; wait for a key (after the global filter)
        add sp, 2
        cmp al, 'L'
        je .done
        cmp al, 'M'
        jne .key
.done:  push ax
        call 0xC4C8:0x0409              ; clear, text mode, INT 43 AX=1
        pop ax
        pop di
        pop si
        pop bp
        retf

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
        cmp dx, [cs:cur+2]              ; at least one sample per column
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
.have:  mov cx, [cs:hi]             ; k = min(hi, bend) - cur (< BUF_W + 1)
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

render:
        push ds
        pop es
        mov di, FB
        mov cx, ROW * 64 / 2
        xor ax, ax
        rep stosw
        xor bx, bx                      ; column
.x:     mov al, [cs:tops+bx]
        mov ah, ROW
        mul ah
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
        mov ax, SND_SEG                 ; invert the start..end columns
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
        mov bx, [cs:xs]
.inv:   cmp bx, ax
        ja .end
        mov di, bx
        shr di, 1
        shr di, 1
        shr di, 1
        add di, FB + TOP * ROW
        mov cl, bl
        and cl, 7
        mov dl, 0x80
        shr dl, cl
        mov cx, BOT - TOP + 1
.iy:    xor [di], dl
        add di, ROW
        loop .iy
        inc bx
        jmp .inv
.end:   ret

align 2
rec:    dw 0
col:    dw 0
xs:     dw 0
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
