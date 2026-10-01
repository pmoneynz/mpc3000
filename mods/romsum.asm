; Minimal staged ROM checksum probe. Reference entry: XA=1, third PGR,
; CS=6900, IF=0. Retain the loader stack, as the working guard does.
; No direct I/O, PGR changes, OS copy, or floppy/NVRAM writes.
; First marker uses only INT 43 AX=4, observed printing the guard.
; Then AX=3 positions report rows; no clear-screen service is used.
bits 16
cpu 8086
org 0

start:
        cli
        cld
        push cs
        pop ds
        mov si, entered
        call puts
        xor bx, bx
        call report_row
        mov si, sum_label
        call puts
        mov ax, 0xF800
        mov es, ax
        xor di, di
        mov cx, 0x4000
        call sum_words
        call hex4

        mov bx, 0x0100
        call report_row
        mov si, lower_label
        call puts
        xor di, di
        mov bp, 4
        call four_blocks
        mov bx, 0x0200
        call report_row
        mov si, upper_label
        call puts
        mov bp, 4
        call four_blocks
        mov bx, 0x0300
        call report_row
        mov si, done
        call puts
.halt: jmp .halt

; BH=row, BL=0. Clear just that row with ordinary spaces, then reposition.
; The initial bottom-row ENTER marker remains visible if positioning hangs.
report_row:
        push ax
        push bx
        push cx
        push di
        push bp
        push ds
        push es
        push bx
        mov ax, 3
        int 0x43
        mov cx, 40
.blank:
        mov bl, ' '
        call putc
        loop .blank
        pop bx
        mov ax, 3
        int 0x43
        pop es
        pop ds
        pop bp
        pop di
        pop cx
        pop bx
        pop ax
        ret

; ES:DI, CX words -> AX sum; DI advances, CX becomes zero.
sum_words:
        xor ax, ax
.next: add ax, [es:di]
        inc di
        inc di
        loop .next
        ret

four_blocks:
        mov cx, 0x800
        call sum_words
        call hex4
        mov bl, ' '
        call putc
        dec bp
        jnz four_blocks
        ret

; Print AX without changing the scan pointer or block counter. Preserve
; registers across INT 43 explicitly, including the string cursor.
hex4:
        push ax
        push bx
        push cx
        push dx
        mov dx, ax
        mov cx, 4
.digit:
        push cx
        mov cl, 4
        rol dx, cl
        mov bl, dl
        and bl, 0x0F
        add bl, '0'
        cmp bl, '9'
        jbe .emit
        add bl, 7
.emit: call putc
        pop cx
        loop .digit
        pop dx
        pop cx
        pop bx
        pop ax
        ret

puts:
        mov bl, [si]
        or bl, bl
        jz .ret
        call putc
        inc si
        jmp puts
.ret:  ret

putc:
        push ax
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
        mov ax, 4
        int 0x43
        pop es
        pop ds
        pop bp
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        pop ax
        ret

entered:     db 13,10,"ROMSUM2 ENTER",0
sum_label:   db "SUM EXP 8634 ACT ",0
lower_label: db "78000+4K: ",0
upper_label: db "7C000+4K: ",0
done:        db "ROMSUM2 DONE - PHOTO / POWER OFF",0
