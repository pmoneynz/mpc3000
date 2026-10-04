; OS 3.16 start-up for the Route C cave (mods/build_wave316.py,
; notes/port_316.md).  The MZ entry point is entry316 in the copy of the cave
; that the EPROM loader placed right after the 3.16 image (3.16 BSS, which its
; own start-up zeroes later).  Loader state: CS = L + stage paragraph, IP =
; entry316, DS = 0040, IF = 0, SS:SP = L+7066:0100, every relocated word
; already holds L + its stored value.
;
; 1. Copy the cave to its home, L + CAVE_HOME.  The cave is org 0, so every
;    offset is the same in both copies.
; 2. Keep 3.16's fixed sequence pool (logical 2000..6FFFE, image 0x48526)
;    below the 3.16 image.  With L = 6900 (3.12 and Vailixi EPROMs) the
;    pool otherwise overlaps image 0..6FFE, and recording overwrites live
;    3.16 code (MAME: Song after recording crashes).  The pool end is the
;    MOV BX,6FFFh immediate at image POOL_INIT_IMM; set it to L-1 when that
;    is lower, so the pool ends at L*16-2.  L = 7000 keeps 6FFFh.
; 3. Jump to 3.16's own entry, L:0000, with DS = 0040 as the loader left it.

entry316:
        cld
        push cs
        pop ds
        mov ax, CAVE_SEG
        RELOC_PREV
        mov es, ax
        xor si, si
        xor di, di
        mov cx, (cave_end - $$ + 1) / 2
        rep movsw
        mov ax, POOL_INIT_IMM >> 4      ; L + paragraph of the immediate
        RELOC_PREV
        mov es, ax
        mov bx, POOL_INIT_IMM & 0x0F
        cmp byte [es:bx-1], 0xBB        ; MOV BX,imm16
        jne .pool_done
        cmp word [es:bx], 0x6FFF
        jne .pool_done
        mov ax, 0xFFFF                  ; L - 1
        RELOC_PREV
        cmp ax, 0x6FFF
        jae .pool_done
        mov [es:bx], ax
.pool_done:
        mov ax, 0x0040
        mov ds, ax
        jmp 0x0000:0x0000               ; 3.16 entry, L:0000
        RELOC_PREV
