; Floppy mod stub: run a patched Vailixi 3.50 OS from RAM.
; See MPC3000/MODDING_HOWTO.md and MPC3000/notes/floppy_loader.md.
;
; Entry (FB93:0066 hand-off): CS = load segment, IP = 0, IF = 0, XA = 1,
; third PGR, so logical 0xB0000-0xF3FFF is RAM and 0xF8000-0xFFFFF is
; the EPROM BIOS. The image after this stub is DGROUP then OS code.

bits 16
org 0

%define CODE_CHUNKS 17                  ; 0x44000 / 0x4000: logical 0xB0000-0xF3FFF
%ifndef DGROUP_BYTES
%define DGROUP_BYTES 0x7C92
%endif

start:
        cli
        cld
        push cs
        pop ds

        ; The relocated OS calls the EPROM BIOS at fixed addresses, so the
        ; BIOS pages must be the ones this OS was built against.
        mov ax, 0xF800
        mov es, ax
        xor si, si
%ifdef EXACT_BIOS_PATH
        mov di, expected_bios
        mov cx, 0x4000
.guard: mov ax, [es:si]
        cmp ax, [di]
        jne wrong_bios
        add si, 2
        add di, 2
        loop .guard
%else
        xor bx, bx
        mov cx, 0x4000
.sum:   add bx, [es:si]
        inc si
        inc si
        loop .sum
        cmp bx, [bios_sum]
        jne wrong_bios
%endif

        ; OS code, top chunk first: every source chunk that a destination
        ; chunk overlaps has a higher index and is already copied.
        mov bp, CODE_CHUNKS
.chunk: dec bp
        mov ax, bp
        mov cl, 10
        shl ax, cl                      ; chunk * 0x400 paragraphs
        mov dx, ax
        mov bx, cs
        add ax, bx
        add ax, [cs:code_para]
        mov ds, ax
        add dx, 0xB000
        mov es, dx
        xor si, si
        xor di, di
        mov cx, 0x2000
        rep movsw
        or bp, bp
        jnz .chunk

        ; DGROUP to 8010:0000, as FAC0:0074 does from ROM at reset.
        mov ax, [cs:dgroup_para]
        mov bx, cs
        add ax, bx
        mov ds, ax
        mov ax, 0x8010
        mov es, ax
        xor si, si
        xor di, di
        mov cx, DGROUP_BYTES / 2
        rep movsw

        ; Rejoin the reset path after the DGROUP copy and second PGR load.
        mov ax, 0x900C
        mov ss, ax
        mov sp, 0x0100
        jmp 0xFAC0:0x0134

wrong_bios:
        mov si, msg
.put:   mov bl, [si]
        or bl, bl
        jz .halt
        mov ax, 4
        int 0x43
        inc si
        jmp .put
.halt:  jmp .halt

%ifdef EXACT_BIOS_PATH
msg:    db 13, 10, "Mod ROM mismatch", 0

align 2
expected_bios:
        incbin EXACT_BIOS_PATH
%else
msg:    db 13, 10, "Mod needs Vailixi 3.50 EPROMs", 0
%endif

; Patched by build_mod_sys.py.
align 2
bios_sum:    dw 0
code_para:   dw 0
dgroup_para: dw 0
