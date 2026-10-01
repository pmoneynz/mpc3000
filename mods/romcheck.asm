; Read-only identity probe for the BIOS left mapped after the floppy loader.
;
; Entry is the INT 45 MZ hand-off: XA=1, third PGR, IF=0.  This program
; does not copy an OS, write a PGR, touch NVRAM, or write the floppy.  It
; compares the complete runtime F800:0000-7FFF window with the 32 KiB
; reference appended to this payload, reports one LCD screen, and stops.

bits 16
cpu 8086
org 0

%ifndef EXPECTED_BIN
    %error "EXPECTED_BIN must name the 32 KiB reference BIOS"
%endif

start:
        cli
        cld
        mov ax, cs
        mov ds, ax
        mov ss, ax
        mov sp, stack_top

        ; Display entry before any ROM reads. Use only the AX=3/4 services
        ; now observed working in the physical ROMSUM2 run.
        mov bh, 7
        mov si, entry_msg
        call print_line

        mov bh, 0
        mov si, stage_sum_start
        call print_line
        mov ax, cs
        mov di, stage_cs
        call hex4
        mov si, stage_sum_start
        call print_line

        ; Actual BIOS 16-bit little-endian additive sum.
        mov ax, 0xF800
        mov es, ax
        xor si, si
        xor bx, bx
        mov cx, 0x4000
.sum:  add bx, [es:si]
        inc si
        inc si
        loop .sum
        mov [actual_sum], bx

        mov bh, 1
        mov si, stage_sum_done
        call print_line

        ; Byte-exact comparison.  Counts are bytes, split into four 8 KiB
        ; regions.  first_diff=FFFF means that no mismatch was observed.
        xor di, di
        mov word [diff_total], 0
        mov word [first_diff], 0xFFFF
        mov word [last_diff], 0
        mov word [quad0], 0
        mov word [quad1], 0
        mov word [quad2], 0
        mov word [quad3], 0
        mov cx, 0x8000
.cmp:  test di, 0x03FF
        jnz .cmp_read
        call compare_progress
.cmp_read:
        mov al, [expected_bios+di]
        cmp al, [es:di]
        je .same
        inc word [diff_total]
        cmp word [first_diff], 0xFFFF
        jne .have_first
        mov [first_diff], di
.have_first:
        mov [last_diff], di
        cmp di, 0x2000
        jb .q0
        cmp di, 0x4000
        jb .q1
        cmp di, 0x6000
        jb .q2
        inc word [quad3]
        jmp .same
.q0:   inc word [quad0]
        jmp .same
.q1:   inc word [quad1]
        jmp .same
.q2:   inc word [quad2]
.same: inc di
        loop .cmp

        mov bh, 2
        mov si, stage_compare_done
        call print_line

        ; CRC-16/CCITT-FALSE of the embedded reference.  Comparing this
        ; runtime result with expected_crc detects a damaged payload before
        ; anyone treats the byte comparison as ROM evidence.
        mov dx, 0xFFFF
        mov si, expected_bios
        mov cx, 0x8000
.crc_byte:
        test cx, 0x0FFF
        jnz .crc_read
        call crc_progress
.crc_read:
        lodsb
        xor dh, al
        mov bp, 8
.crc_bit:
        shl dx, 1
        jnc .crc_no_xor
        xor dx, 0x1021
.crc_no_xor:
        dec bp
        jnz .crc_bit
        loop .crc_byte
        mov [ref_crc_actual], dx

        mov bh, 3
        mov si, stage_crc_done
        call print_line

        ; Fill the fixed 40x8 report template.
        mov ax, [expected_sum]
        mov di, line1+8
        call hex4
        mov ax, [actual_sum]
        mov di, line1+17
        call hex4

        mov ax, [expected_crc]
        mov di, line2+12
        call hex4
        mov ax, [ref_crc_actual]
        mov di, line2+21
        call hex4
        cmp ax, [expected_crc]
        je .crc_ok
        mov byte [line2+26], 'B'
        mov byte [line2+27], 'A'
        mov byte [line2+28], 'D'
.crc_ok:

        mov byte [line3+5], '0'
        mov ax, [diff_total]
        mov di, line3+6
        call hex4

        mov byte [line4+3], '0'
        mov ax, [quad0]
        mov di, line4+4
        call hex4
        mov byte [line4+9], '0'
        mov ax, [quad1]
        mov di, line4+10
        call hex4
        mov byte [line4+15], '0'
        mov ax, [quad2]
        mov di, line4+16
        call hex4
        mov byte [line4+21], '0'
        mov ax, [quad3]
        mov di, line4+22
        call hex4

        mov ax, [first_diff]
        cmp ax, 0xFFFF
        je .no_diff
        mov di, line3+17
        call linear_offset
        mov ax, [last_diff]
        mov di, line3+28
        call linear_offset
        mov ax, [first_diff]
        cmp ax, 0x7FF8
        jbe .sample_ready
        mov ax, 0x7FF8
        jmp .sample_ready
.no_diff:
        xor ax, ax
.sample_ready:
        mov [sample_off], ax
        mov di, line5+4
        call linear_offset

        ; Eight contiguous bytes beginning at the first mismatch.  At the
        ; top of the window the start is clamped to 7FF8 so all eight exist.
        mov si, [sample_off]
        mov di, line5+14
        mov cx, 8
.exp_bytes:
        mov al, [expected_bios+si]
        call hex_byte
        inc si
        loop .exp_bytes
        mov si, [sample_off]
        mov di, line6+14
        mov cx, 8
.got_bytes:
        mov al, [es:si]
        call hex_byte
        inc si
        loop .got_bytes

        mov bh, 4
        mov si, stage_format_done
        call print_line

        ; AX=3 positions BH=row, BL=column; AX=4 writes ordinary spaces
        ; and text. No clear-screen service or direct port access.
        mov bh, 0
        mov si, line0
        call print_line
        mov bh, 1
        mov si, line1
        call print_line
        mov bh, 2
        mov si, line2
        call print_line
        mov bh, 3
        mov si, line3
        call print_line
        mov bh, 4
        mov si, line4
        call print_line
        mov bh, 5
        mov si, line5
        call print_line
        mov bh, 6
        mov si, line6
        call print_line
        mov bh, 7
        mov si, line7
        call print_line
.halt: cli
        jmp .halt

; Loop-boundary markers keep the scan state and flags intact. The value
; is the next window byte offset, not a physical or linear-file address.
compare_progress:
        pushf
        push ax
        push bx
        push si
        push di
        mov ax, di
        mov di, stage_compare_offset
        mov si, stage_compare_progress
        mov bh, 2
        call hex4
        call print_line
        pop di
        pop si
        pop bx
        pop ax
        popf
        ret

crc_progress:
        pushf
        push ax
        push bx
        push si
        push di
        mov ax, 0x8000
        sub ax, cx
        mov di, stage_crc_offset
        mov si, stage_crc_progress
        mov bh, 3
        call hex4
        call print_line
        pop di
        pop si
        pop bx
        pop ax
        popf
        ret

; AX is a BIOS-window byte offset.  The corresponding linear ROM file
; offset is 0x78000+AX, represented as '7' plus hex(0x8000+AX).
linear_offset:
        mov byte [di], '7'
        inc di
        add ax, 0x8000
        jmp hex4

; AX -> four uppercase hexadecimal characters at DS:DI.
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
        call hex_nibble
        mov [di], al
        inc di
        dec dx
        jnz .digit
        pop dx
        pop cx
        pop bx
        pop ax
        ret

; AL -> two uppercase hexadecimal characters at DS:DI.
hex_byte:
        push ax
        mov ah, al
        shr al, 1
        shr al, 1
        shr al, 1
        shr al, 1
        call hex_nibble
        mov [di], al
        inc di
        mov al, ah
        and al, 0x0F
        call hex_nibble
        mov [di], al
        inc di
        pop ax
        ret

hex_nibble:
        add al, '0'
        cmp al, '9'
        jbe .ret
        add al, 7
.ret:  ret

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
.next: lodsb
        or al, al
        jz .done
        mov bl, al
        mov ax, 4
        call lcd_call
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

actual_sum:     dw 0
ref_crc_actual: dw 0
diff_total:    dw 0
first_diff:    dw 0
last_diff:     dw 0
quad0:         dw 0
quad1:         dw 0
quad2:         dw 0
quad3:         dw 0
sample_off:    dw 0

; Patched by build_romcheck.py after assembly.
expected_sum:  dw 0
expected_crc:  dw 0

entry_msg: db "ROMCHECK4 ENTER", 0
stage_sum_start: db "RC4 1 ENTRY RETURNED - SUM CS="
stage_cs: db "----", 0
stage_sum_done: db "RC4 2 SUM DONE - COMPARE START", 0
stage_compare_progress: db "RC4 COMPARE NEXT OFFSET "
stage_compare_offset: db "----", 0
stage_compare_done: db "RC4 3 COMPARE DONE - CRC START", 0
stage_crc_progress: db "RC4 CRC NEXT OFFSET "
stage_crc_offset: db "----", 0
stage_crc_done: db "RC4 4 CRC DONE - FORMAT START", 0
stage_format_done: db "RC4 5 FORMAT DONE - REPORT START", 0
line0: db "ROMCHECK4 STOP", 0
line1: db "SUM EXP XXXX ACT XXXX", 0
line2: db "REF CRC EXP XXXX ACT XXXX OK ", 0
line3: db "DIFF 00000 FIRST ----- LAST -----", 0
line4: db "8K 00000 00000 00000 00000", 0
line5: db "OFF ----- EXP:----------------", 0
line6: db "          GOT:----------------", 0
line7: db "NO OS COPY - POWER OFF / PHOTO", 0

align 2
stack_bottom:
        times 512 db 0
stack_top:

align 2
expected_bios:
        incbin EXPECTED_BIN
expected_bios_end:
