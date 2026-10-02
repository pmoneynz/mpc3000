; Capture the physical machine's application/DGROUP ROM window to the
; preallocated ROMAPP.BIN. Entry is the INT 45 MZ hand-off: XA=1, third
; PGR, IF=0, DS=0040, ES=CS, ICU last written C011=FF.
;
; The exact captured high BIOS is embedded as a guard. A real INT 12 frame
; then enters a local handler which stages IVT[12], RETXA-switches to XA=0,
; and enters the captured FAC0:01C6 first-PGR loader. Its BRKXA 12 returns
; through captured FAC0:024F. After one 16 KiB ROM page is copied with
; aligned word reads, INT 10 restores the third PGR before any INT 41 call.
;
; Source pages are exactly logical A0000-F3FFF under the first PGR:
; linear file [20000,74000). F4000-F7FFF is deliberately excluded because
; first-PGR slot 61 maps the NVRAM window, not ROM.

bits 16
cpu 8086
org 0

%ifndef EXPECTED_BIOS
    %error "EXPECTED_BIOS must name the exact 32 KiB hardware BIOS capture"
%endif

%define PAGE_COUNT       0x0015
%define PAGE_WORDS       0x2000
%define SECTORS_PER_PAGE 0x0020

start:
        cli
        cld
        push cs
        pop ds

        ; Earliest marker: before cursor positioning, ROM scans, PGR changes,
        ; or disk calls.
        mov si, entered
        call puts
        xor bx, bx
        mov si, title
        call show_line
        mov bx, 0x0100
        mov si, range_line
        call show_line
        mov bx, 0x0200
        mov si, guard_line
        call show_line

        ; Exact word-by-word guard of the runtime-visible high BIOS. Every
        ; ROM read is aligned. This also guards the XA/PGR trampoline bytes.
        mov ax, 0xF800
        mov es, ax
        xor si, si
        mov di, expected_bios
        mov cx, 0x4000
.guard:
        mov ax, [es:si]
        cmp ax, [di]
        jne fail_guard
        add si, 2
        add di, 2
        loop .guard

        ; Restore the loader-observed ICU value for all file calls. The
        ; device/bit meaning remains an unknown hardware boundary.
        mov dx, 0xC011
        mov al, 0xF6
        out dx, al

        mov dx, filename
        mov ax, 2
        int 0x41
        cli
        or ah, ah
        jnz fail_open
        mov [handle], ax
        mov byte [handle_open], 1

        mov word [page_index], 0
        mov word [running_sum], 0

.page:
        mov si, read_line
        call show_page_status

        ; Returns under XA=1 with the first PGR active. Program, inherited
        ; stack, IVT, and buffer are in pages 0-39, which are identical RAM
        ; mappings in the first and third tables.
        call switch_first_pgr

        ; Page n: segment A000 + n*0400, offset 0000-3FFF.
        mov ax, [page_index]
        mov cl, 10
        shl ax, cl
        add ax, 0xA000
        mov es, ax
        xor si, si
        mov di, buffer
        mov cx, PAGE_WORDS
        mov bp, [running_sum]
.copy_words:
        mov ax, [es:si]
        mov [di], ax
        add bp, ax
        add si, 2
        add di, 2
        loop .copy_words
        mov [running_sum], bp

        ; Captured FAC0:01A4/01BD reloads the third PGR and returns through
        ; FAC0:024F. No disk or display call occurs while the first PGR is live.
        int 0x10
        cli

        mov si, write_line
        call show_page_status
        mov word [write_offset], buffer
        mov word [sectors_left], SECTORS_PER_PAGE
.write_sector:
        mov bx, [handle]
        mov dx, [write_offset]
        mov cx, 0x0200
        mov ax, 5
        int 0x41
        cli
        or ax, ax
        jnz fail_write
        cmp cx, 0x0200
        jne fail_short
        add word [write_offset], 0x0200
        dec word [sectors_left]
        jnz .write_sector

        inc word [page_index]
        cmp word [page_index], PAGE_COUNT
        jb .page

        mov bx, [handle]
        mov ax, 3
        int 0x41
        cli
        mov byte [handle_open], 0
        or ah, ah
        jnz fail_close

        call restore_entry_icu
        mov bx, 0x0200
        mov si, complete_line
        call show_line
        mov bx, 0x0300
        mov si, done_line
        call show_line
        mov bx, 0x0400
        mov si, sum_line
        call show_line
        mov bx, 0x0409
        mov ax, 3
        int 0x43
        mov ax, [running_sum]
        call hex4
.halt:
        cli
        jmp .halt

; Install a local INT 12 target in translated RAM. INT supplies the sole
; FLAGS/CS/IP frame which captured FAC0:024F ultimately consumes.
switch_first_pgr:
        push ax
        push es
        xor ax, ax
        mov es, ax
        mov word [es:0x0048], first_pgr_handler
        mov ax, cs
        mov word [es:0x004A], ax
        int 0x12
        cli
        pop es
        pop ax
        ret

; Entered by INT 12 under XA=1. Push exactly the registers popped by the
; captured FAC0:024F wrapper, stage its XA=0 loop, then switch without
; adding another interrupt frame.
first_pgr_handler:
        cli
        push ds
        push si
        push ax
        push bx
        push cx
        push dx
        xor ax, ax
        mov ds, ax
        mov word [0x0048], 0x01C6
        mov word [0x004A], 0xFAC0
        mov si, 0x0256
        mov cx, 0x0040
        mov dx, 0xFF00
        db 0x0F, 0xF0, 0x12          ; RETXA 12 -> FAC0:01C6 under XA=0

fail_guard:
        mov byte [error_kind], 'G'
        mov [error_ax], si
        mov [error_cx], ax
        jmp fail
fail_open:
        mov byte [error_kind], 'O'
        jmp fail_save
fail_write:
        mov byte [error_kind], 'W'
        jmp fail_save
fail_short:
        mov byte [error_kind], 'S'
        xor ax, ax
        jmp fail_save
fail_close:
        mov byte [error_kind], 'C'
fail_save:
        mov [error_ax], ax
        mov [error_cx], cx

fail:
        cmp byte [handle_open], 0
        je .restored
        ; Every reachable file error occurs after INT 10 restored the third
        ; PGR. Close is therefore attempted on open/write/short failures.
        mov bx, [handle]
        mov ax, 3
        int 0x41
        cli
        mov byte [handle_open], 0
.restored:
        call restore_entry_icu
        mov bx, 0x0200
        mov si, error_stage
        call show_line
        mov bx, 0x0300
        mov si, error_prefix
        call show_line
        mov bx, 0x030D
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
        mov si, error_page_label
        call puts
        mov ax, [page_index]
        call hex2
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

; DS:SI selects a 40-cell template containing page placeholder 00 at col 5.
show_page_status:
        push ax
        push bx
        mov bx, 0x0200
        call show_line
        mov bx, 0x0205
        mov ax, 3
        int 0x43
        mov ax, [page_index]
        call hex2
        pop bx
        pop ax
        ret

; BH=row, BL=column, DS:SI=NUL string. Emit exactly 40 cells.
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

hex2:
        ; Page index is <=14h, so render the low byte.
        call hex_byte
        ret

hex4:
        push ax
        mov al, ah
        call hex_byte
        pop ax
        call hex_byte
        ret

hex_byte:
        push ax
        push bx
        push cx
        mov bh, al
        mov cl, 4
        shr al, cl
        call hex_nibble
        mov al, bh
        and al, 0x0F
        call hex_nibble
        pop cx
        pop bx
        pop ax
        ret

hex_nibble:
        and al, 0x0F
        add al, '0'
        cmp al, '9'
        jbe .emit
        add al, 7
.emit:
        mov bl, al
        call putc
        ret

handle:          dw 0
handle_open:     db 0
error_kind:      db '?'
page_index:      dw 0
sectors_left:    dw 0
write_offset:    dw 0
running_sum:     dw 0
error_ax:        dw 0
error_cx:        dw 0

filename:         db "ROMAPP  BIN", 0
entered:          db 13, 10, "ROMAPP ENTER - DO NOT REMOVE USB", 0
title:            db "ROMAPP PHYSICAL ROM CAPTURE", 0
range_line:       db "FILE 20000-73FFF / F400 PAGE EXCLUDED", 0
guard_line:       db "GUARD EXACT HIGH BIOS", 0
read_line:        db "PAGE 00/14 READ FIRST PGR", 0
write_line:       db "PAGE 00/14 WRITE THIRD PGR", 0
complete_line:    db "21 PAGES / 336K WRITTEN", 0
done_line:        db "ROMAPP DONE - POWER OFF / KEEP USB", 0
sum_line:         db "WORD SUM ", 0
error_stage:      db "ROMAPP TERMINATED AFTER SAFE RESTORE", 0
error_prefix:     db "ROMAPP ERROR ", 0
error_ax_label:   db " AX=", 0
error_cx_label:   db " CX=", 0
error_page_label: db " P=", 0
error_stop:       db "NO DONE - POWER OFF / KEEP USB", 0

align 2
buffer:
        times 0x4000 db 0
buffer_end:

align 2
expected_bios:
        incbin EXPECTED_BIOS
expected_bios_end:
