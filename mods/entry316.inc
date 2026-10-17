; OS 3.16 start-up for the Route C cave (mods/build_wave316.py,
; notes/port_316.md "Cave space").  The MZ entry point is entry316 in the copy
; of the cave that the EPROM loader placed right after the 3.16 image (3.16
; BSS, which its own start-up zeroes later).  Loader state: CS = L + stage
; paragraph, IP = entry316, DS = 0040, ES = CS, IF = 0, SS:SP = L+7066:0100,
; every relocated word already holds L + its stored value
; (notes/floppy_loader.md §5, §7).
;
; Universal layout.  3.16 runs at UNIV_SEG (6900h) on every EPROM set:
;
; 0. L > UNIV_SEG (3.08, 3.11: L = 7000h): .move takes 3.16 down to
;    UNIV_SEG, with L - UNIV_SEG = D paragraphs:
;    a. every relocated word (reloc_table, built from the MZ relocation
;       list) gets -D, so the image holds the words the loader writes with
;       L = UNIV_SEG;
;    b. the whole loaded image (N = reloc_table+0 paragraphs, this routine and
;       the table included) is copied from L:0 to UNIV_SEG:0, low to high
;       (destination below source: forward copy is safe), in 800h-paragraph
;       chunks;
;    c. the loader's records of L are rebased: BIOS data 0040:640A (INT 45's
;       load segment), 0040:68C2 (the hand-off's JMP FAR segment) and SS;
;    d. a far jump continues in the moved copy at .moved, which zeroes the
;       D paragraphs the image left (UNIV_SEG+N up to L+N, this routine's old
;       copy among them) and restarts entry316, which now reads L-1 =
;       UNIV_SEG-1 and runs steps 1-3 as on a 3.12 / 3.50 machine.
;    The copy never reaches the code that runs it: the builder sets
;    reloc_table+4 (least D) so that UNIV_SEG+N <= L + the paragraph of
;    entry316; a smaller D halts.  No stack is used (IF = 0; no PUSH, CALL or
;    INT), and BP is kept as the loader left it.
; 1. Copy the cave to its home, L + CAVE_HOME.  The cave is org 0, so every
;    offset is the same in both copies.
; 2. Keep 3.16's fixed sequence pool (logical 2000..6FFFE, image 0x48526)
;    below the 3.16 image.  At L <= 6900h the pool otherwise overlaps image
;    0..6FFE, and recording overwrites live 3.16 code (MAME: Song after
;    recording crashes).  The pool end is the MOV BX,6FFFh immediate at image
;    POOL_INIT_IMM; set it to L-1 - SCSI_STK_PARAS, so the pool ends at L*16
;    - 2 - the stack: the SCSI_STK_PARAS paragraphs above it, up to the image,
;    hold the private stack of the SCSI partition reader (scsistack316.inc).
; 3. Jump to 3.16's own entry, L:0000, with DS = 0040 as the loader left it.
;
; Steps 1-3 run only with L <= UNIV_SEG; the builder checks that the home at
; UNIV_SEG + CAVE_HOME ends below page 61 (logical F4000h, NVRAM).

UNIV_SEG equ 0x6900                     ; the 3.12 / 3.50 load segment

entry316:
        cld
        mov dx, 0xFFFF                  ; L - 1
        RELOC_PREV
        cmp dx, UNIV_SEG - 1
        ja .move
        push cs
        pop ds
        mov ax, CAVE_SEG
        RELOC_PREV
        mov es, ax
        xor si, si
        xor di, di
        mov cx, (cave_copy_end - $$ + 1) / 2
        rep movsw
        mov ax, POOL_INIT_IMM >> 4      ; L + paragraph of the immediate
        RELOC_PREV
        mov es, ax
        mov bx, POOL_INIT_IMM & 0x0F
        cmp byte [es:bx-1], 0xBB        ; MOV BX,imm16
        jne .pool_done
        cmp word [es:bx], 0x6FFF
        jne .pool_done
        mov ax, dx                      ; L - 1
        sub ax, SCSI_STK_PARAS          ; room for the SCSI reader's stack
        mov [es:bx], ax                 ; (scsistack316.inc) below the image
.pool_done:
        mov ax, 0x0040
        mov ds, ax
        jmp 0x0000:0x0000               ; 3.16 entry, L:0000
        RELOC_PREV
.halt:
        hlt                             ; IF = 0: stays here
        jmp short .halt

.move:                                  ; CS = L + stage; no relocated word is read from here on
        mov bx, dx
        sub bx, UNIV_SEG - 1            ; BX = D = L - UNIV_SEG
        cmp bx, [cs:reloc_table + 4]
        jb .halt                        ; the copy would reach this code
        mov ax, cs
        mov ds, ax
        mov si, reloc_table + 6
        mov cx, [reloc_table + 2]       ; records
        mov ax, dx
        inc ax
        mov es, ax                      ; ES:DI = L:0000, the image's first byte
        xor di, di
.rr:    lodsb                           ; a. one record: advance, then maybe -D
        mov ah, 0
        test al, al
        jnz .rr_word                    ; 01..FF: advance that many bytes
        lodsw
        test ax, ax
        jnz .rr_word                    ; 00 w: advance w bytes (w <= FFF0h)
        add di, 0xFFF0                  ; 00 0000: advance FFF0h, no word
        mov ax, di
        shr ax, 4
        and di, 0x000F
        mov dx, es
        add ax, dx
        mov es, ax
        jmp short .rr_next
.rr_word:
        add di, ax
        mov ax, di
        shr ax, 4
        and di, 0x000F
        mov dx, es
        add ax, dx
        mov es, ax
        sub [es:di], bx                 ; relocated word: L + v -> UNIV_SEG + v
.rr_next:
        loop .rr
        mov dx, [reloc_table]           ; b. N paragraphs
        mov ax, UNIV_SEG
        mov es, ax
        add ax, bx
        mov ds, ax                      ; DS = L
.mv:    mov cx, 0x0800
        cmp dx, cx
        jae .mv_full
        mov cx, dx
.mv_full:
        sub dx, cx
        shl cx, 3                       ; words
        xor si, si
        xor di, di
        rep movsw
        mov ax, ds
        add ax, 0x0800
        mov ds, ax
        mov ax, es
        add ax, 0x0800
        mov es, ax
        test dx, dx
        jnz .mv
        mov ax, 0x0040                  ; c. the loader's records of L
        mov ds, ax
        mov ax, UNIV_SEG
        add ax, bx                      ; L
        cmp [0x640A], ax
        jne .bios_seg
        sub [0x640A], bx                ; INT 45: load segment
.bios_seg:
        mov ax, cs
        cmp [0x68C2], ax
        jne .bios_done
        sub [0x68C2], bx                ; hand-off: JMP FAR [68C0] segment
.bios_done:
        mov ax, ss
        sub ax, bx
        mov ss, ax                      ; SS = UNIV_SEG + e_ss, SP kept
        mov ax, .moved
        mov [cs:.moved_ptr], ax
        mov ax, cs
        sub ax, bx
        mov [cs:.moved_ptr + 2], ax
        jmp far [cs:.moved_ptr]         ; d. into the moved copy

.moved:                                 ; CS = UNIV_SEG + stage, BX = D
        mov ax, cs
        mov ds, ax
        mov ax, UNIV_SEG
        add ax, [reloc_table]
        mov es, ax                      ; UNIV_SEG + N: the paragraphs the image left
        xor ax, ax
.zero:  xor di, di
        mov cx, 0x0800
        cmp bx, cx
        jae .zero_full
        mov cx, bx
.zero_full:
        sub bx, cx
        shl cx, 3
        rep stosw
        mov dx, es
        add dx, 0x0800
        mov es, dx
        test bx, bx
        jnz .zero
        jmp entry316                    ; now L - 1 = UNIV_SEG - 1

align 2
.moved_ptr:
        dw 0, 0                         ; far pointer to .moved, written by .move in the old copy

; Relocation table, appended here by the builder (route_c.build): every
; MZ-relocated word of the image, in image order.  It is the last thing in
; the image, never copied home, and read only by .move and .moved, which
; run before 3.16's start-up zeroes BSS (DGROUP:7980..FC9E, image
; 0x68340..0x7065E, which holds the stage).
;   +0 dw N     paragraphs from the image start to the table end
;   +2 dw R     records
;   +4 dw Dmin  least L - UNIV_SEG the move may run with
;   +6 records  01..FF: advance that many bytes, the word there gets -D;
;               00 w (w != 0): advance w bytes, the word there gets -D;
;               00 0000: advance FFF0h bytes only.
; The first record's advance starts at image offset 0.
align 2
reloc_table:
