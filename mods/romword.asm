; Focused word comparison of F800:2000-3FFF against linear 7A000-7BFFF.
; Retain the loader stack and IF=0. All ROM/reference reads are aligned
; words. Counts and first/last offsets stay in registers during the scan.
; Only INT 43 AX=3/4 output; no direct I/O, mapping changes or OS copies.
bits 16
cpu 8086
org 0
%ifndef EXPECTED_BIN
    %error "EXPECTED_BIN required"
%endif

start:
        cli
        cld
        push cs
        pop ds
        mov ax, cs
        mov di, entry_cs
        call hex4
        mov bh, 7
        mov si, entry_text
        call print_line

        xor bx, bx
        mov si, expected_bios
        mov cx, 0x1000
.refsum:
        add bx, [si]
        add si, 2
        loop .refsum
        mov ax, bx
        mov di, ref_actual
        call hex4
        push bx
        mov bh, 0
        mov si, ref_text
        call print_line
        pop bx
        cmp bx, 0x11F8
        je .reference_ok
        jmp bad_reference
.reference_ok:

        mov ax, 0xF800
        mov es, ax
        mov si, expected_bios
        mov di, 0x2000
        mov cx, 0x1000
        xor bx, bx
        mov bp, 0xFFFF
        mov dx, 0xFFFF
.compare:
        test di, 0x00FF
        jnz .read
        call progress
.read: mov ax, [si]
        cmp ax, [es:di]
        je .same
        inc bx
        cmp bp, 0xFFFF
        jne .seen
        mov bp, di
        call show_first
.seen: mov dx, di
.same: add si, 2
        add di, 2
        loop .compare

        mov ax, bx
        mov di, count_value
        call hex4
        cmp bp, 0xFFFF
        je .no_diff
        mov ax, bp
        mov di, first_value
        call file_offset
        mov ax, dx
        mov di, last_value
        call file_offset
        mov ax, bp
        cmp ax, 0x3FF8
        jbe .sample
        mov ax, 0x3FF8
        jmp .sample
.no_diff:
        mov ax, 0x2000
.sample:
        mov [sample_offset], ax
        mov di, sample_value
        call file_offset
        mov si, [sample_offset]
        mov di, expected_words
        mov cx, 4
.expected:
        mov ax, [expected_bios+si-0x2000]
        call hex4
        inc di
        add si, 2
        loop .expected
        mov si, [sample_offset]
        mov di, actual_words
        mov cx, 4
.actual:
        mov ax, [es:si]
        call hex4
        inc di
        add si, 2
        loop .actual

        mov bh, 1
        mov si, compared_text
        call print_line
        mov bh, 3
        mov si, count_text
        call print_line
        mov bh, 4
        mov si, expected_text
        call print_line
        mov bh, 5
        mov si, actual_text
        call print_line
        mov bh, 6
        mov si, done_text
        call print_line
halt:  jmp halt

bad_reference:
        mov bh, 6
        mov si, bad_text
        call print_line
        jmp halt

progress:
        pushf
        push ax
        push bx
        push si
        push di
        mov ax, di
        mov di, progress_value
        call hex4
        mov bh, 1
        mov si, progress_text
        call print_line
        pop di
        pop si
        pop bx
        pop ax
        popf
        ret

; Publish the first differing word before continuing any scan work.
show_first:
        pushf
        push ax
        push bx
        push si
        push di
        mov ax, bp
        mov di, immediate_offset
        call file_offset
        mov ax, [si]
        mov di, immediate_expected
        call hex4
        mov si, bp
        mov ax, [es:si]
        mov di, immediate_actual
        call hex4
        mov bh, 2
        mov si, immediate_text
        call print_line
        pop di
        pop si
        pop bx
        pop ax
        popf
        ret

file_offset:
        mov byte [di], '7'
        inc di
        add ax, 0x8000
        jmp hex4

hex4:
        push ax
        push bx
        push cx
        push dx
        mov bx, ax
        mov dx, 4
        mov cl, 4
.digit:
        rol bx, cl
        mov al, bl
        and al, 0x0F
        add al, '0'
        cmp al, '9'
        jbe .store
        add al, 7
.store:
        mov [di], al
        inc di
        dec dx
        jnz .digit
        pop dx
        pop cx
        pop bx
        pop ax
        ret

print_line:
        push ax
        push bx
        push cx
        push si
        xor bl, bl
        push bx
        mov ax, 3
        call lcd_call
        mov cx, 40
.blank:
        mov bl, ' '
        mov ax, 4
        call lcd_call
        loop .blank
        pop bx
        mov ax, 3
        call lcd_call
.next: mov bl, [si]
        or bl, bl
        jz .done
        mov ax, 4
        call lcd_call
        inc si
        jmp .next
.done: pop si
        pop cx
        pop bx
        pop ax
        ret

lcd_call:
        push ax
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
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

sample_offset: dw 0
entry_text: db "ROMWORD5 ENTER CS="
entry_cs: db "----",0
ref_text: db "REF WORDSUM EXP 11F8 ACT "
ref_actual: db "----",0
progress_text: db "WORD5 NEXT ROM OFFSET "
progress_value: db "----",0
immediate_text: db "FIRST "
immediate_offset: db "----- EXP "
immediate_expected: db "---- GOT "
immediate_actual: db "----",0
compared_text: db "WORD5 COMPARED 7A000-7BFFF",0
count_text: db "WORDS "
count_value: db "---- FIRST "
first_value: db "----- LAST "
last_value: db "-----",0
expected_text:
sample_value: db "----- EXP: "
expected_words: db "---- ---- ---- ----",0
actual_text: db "      GOT: "
actual_words: db "---- ---- ---- ----",0
done_text: db "ROMWORD5 DONE - PHOTO / POWER OFF",0
bad_text: db "REFERENCE BAD - PHOTO / POWER OFF",0

align 2
expected_bios:
        incbin EXPECTED_BIN
expected_bios_end:
