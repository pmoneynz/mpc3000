; Capture the runtime-visible high 32 KiB ROM window to a preallocated
; BIOS.BIN on the same floppy image. Entry is the INT 45 MZ hand-off:
; XA=1, third PGR, IF=0, DS=0040, ES=CS, ICU last written C011=FF.
;
; Every ROM access is an aligned word read into a 512-byte RAM buffer.
; INT 41 writes only from that buffer. The program never writes a PGR,
; ROM, or NVRAM and does not request FAT allocation. BIOS close behavior
; may still update directory metadata on the already allocated file.

bits 16
cpu 8086
org 0

start:
        cli
        cld
        push cs
        pop ds

        ; This marker precedes cursor positioning, ROM reads, and disk writes.
        mov si, entered
        call puts
        xor bx, bx
        mov si, title
        call show_line
        mov bx, 0x0100
        mov si, range_line
        call show_line
        mov bx, 0x0200
        mov si, writing
        call show_line
        mov bx, 0x020C
        mov ax, 3
        int 0x43

        ; Restore the exact ICU port value used by the loader while it read
        ; the SYS. Device/bit meaning is deliberately not asserted here.
        mov dx, 0xC011
        mov al, 0xF6
        out dx, al

        ; Open the preallocated file. INT 41 enables interrupts internally.
        mov dx, filename
        mov ax, 2
        int 0x41
        cli
        or ah, ah
        jnz fail_open
        mov [handle], ax

        mov ax, 0xF800
        mov es, ax
        xor si, si
        mov word [running_sum], 0
        mov word [chunks_done], 0

.chunk:
        mov di, buffer
        mov cx, 0x0100
        mov bp, [running_sum]
.copy_words:
        mov ax, [es:si]
        mov [di], ax
        add bp, ax
        add si, 2
        add di, 2
        loop .copy_words
        mov [running_sum], bp

        ; Sequential write. BIOS.BIN is already 32 KiB and fully allocated.
        mov bx, [handle]
        mov dx, buffer
        mov cx, 0x0200
        mov ax, 5
        int 0x41
        cli
        or ax, ax
        jnz fail_write
        cmp cx, 0x0200
        jne fail_short

        inc word [chunks_done]
        test word [chunks_done], 7
        jnz .not_4k
        mov bl, '.'
        call putc
.not_4k:
        cmp word [chunks_done], 0x0040
        jb .chunk

        ; Close is required to flush the final dirty sector and directory state.
        mov bx, [handle]
        mov ax, 3
        int 0x41
        cli
        mov word [handle], 0
        or ah, ah
        jnz fail_close

        call restore_entry_icu
        mov bx, 0x0300
        mov si, done_line
        call show_line
        mov bx, 0x0400
        mov si, sum_label
        call show_line
        mov bx, 0x0409
        mov ax, 3
        int 0x43
        mov ax, [running_sum]
        call hex4
.halt:
        cli
        jmp .halt

fail_open:
        mov byte [error_kind], 'O'
        jmp fail
fail_write:
        mov byte [error_kind], 'W'
        jmp fail
fail_short:
        mov byte [error_kind], 'S'
        xor ax, ax
        jmp fail
fail_close:
        mov byte [error_kind], 'C'

fail:
        mov [error_ax], ax
        mov [error_cx], cx
        cmp word [handle], 0
        je .restored
        mov bx, [handle]
        mov ax, 3
        int 0x41
        cli
        mov word [handle], 0
.restored:
        call restore_entry_icu
        mov bx, 0x0300
        mov si, error_prefix
        call show_line
        mov bx, 0x030E
        mov ax, 3
        int 0x43
        mov bl, [error_kind]
        call putc
        mov si, error_ax_label
        call puts
        mov ax, [error_ax]
        call hex4
        mov si, error_cx_label
        call puts
        mov ax, [error_cx]
        call hex4
        mov bx, 0x0400
        mov si, error_stop
        call show_line
        jmp start.halt

restore_entry_icu:
        cli
        mov dx, 0xC011
        mov al, 0xFF
        out dx, al
        ret

; BH=row, BL=column, DS:SI=NUL string. Emit all 40 cells so a shorter
; status cannot blend with text already on the LCD row.
show_line:
        push ax
        push bx
        push cx
        push si
        mov ax, 3
        int 0x43
        mov cx, 40
.next:
        mov bl, [si]
        or bl, bl
        jz .blank
        inc si
        jmp .emit
.blank:
        mov bl, ' '
.emit:
        call putc
        loop .next
        pop si
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

; AX -> four uppercase hexadecimal characters.
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

handle:         dw 0
chunks_done:    dw 0
running_sum:    dw 0
error_ax:       dw 0
error_cx:       dw 0
error_kind:     db '?'

; INT 41 AX=2 consumes the MPC fixed 8-byte name + 3-byte extension object.
filename:       db "BIOS    BIN", 0
entered:        db 13, 10, "ROMDUMP ENTER - DO NOT REMOVE USB", 0
title:          db "ROMDUMP HIGH ROM CAPTURE", 0
range_line:     db "F800:0000-7FFF -> BIOS.BIN", 0
writing:        db "WRITING 32K ", 0
done_line:      db "ROMDUMP DONE - POWER OFF / KEEP USB", 0
sum_label:      db "WORD SUM ", 0
error_prefix:   db "ROMDUMP ERROR ", 0
error_ax_label: db " AX=", 0
error_cx_label: db " CX=", 0
error_stop:     db "NO DONE - POWER OFF / KEEP USB", 0

align 2
buffer:
        times 0x0200 db 0
buffer_end:
