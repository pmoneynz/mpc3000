; Program/Sounds 9: Compression, ported from Vailixi 3.50 (page C887:1C6E,
; engine C887:1FC9; file 0x4A4DE / 0x4A839).  OS 3.16 only (PROFILE_316):
; Vailixi has it natively.  Port specification: notes/vailixi_port.md.
;
; As in Vailixi, option 9 of the Program/Sounds menu becomes compression (menu
; text "9.Compress sound") and MIDI sample dump leaves the menu: WAVE316.args replaces the menu text and
; the option-9 arm's CALLF 46A4:000C (image 0x1A085) with CALLF compress_page.
;
; Compression keeps every other sample (out[k] = in[2k], no filter), halves
; Length, Soft st and Soft end, and lowers Tune by 120 (one octave at 0.1
; semitone per unit), so the sound plays at the same pitch from half the
; memory; the allocator rebuild then counts the freed half as free.
;
; Deviations from Vailixi (port spec D-1..D-9):
;   - a chunk whose output is empty is not written (Vailixi passes count 0 to
;     the wave transfer, which then runs 65,536 passes);
;   - stereo planes are decimated separately (Vailixi's single stream puts
;     the left plane's last sample at the start of the right one when the
;     length is odd);
;   - the transfer buffer is SND_SEG:0000, BUF_W words, with BUSY held, as in
;     the stock loader, Best st and the wave view's fill;
;   - results shorter than 441 frames are refused (the stock loader clamps
;     shorter lengths without reallocating);
;   - Tune may be set up to +120 here (Vailixi +60), so a field redraw never
;     clamps the value compressed from;
;   - sounding voices are stopped first, a zone map of the sound is dropped,
;     and a Tune commit with no sounds writes nothing.

COMPRESS_TUNE_MAX   equ 120
COMPRESS_MIN_FRAMES equ 441

; FAR, from the menu arm: DS = DGROUP, transport already stopped by the arm's
; first call.  Returns AX = the key that left the page.  Keeps BP, SI, DI, DS.
; Frame as Vailixi's: [bp-1] list position, [bp-2] sound index during Do it,
; [bp-4] Tune shadow (word), [bp-84h] 128 sorted indexes, [bp-288h] 129 far
; pointers to their names.
compress_page:
        push bp
        mov bp, sp
        sub sp, 0x288
        push si
        push di
        xor dx, dx
        jmp .leave_test

.redraw:
        mov bx, cmp_s_title
        call du_title                    ; field list reset, clear, "== Compress Sound =="
        mov al, 1
        call du_at                       ; cursor row 1, column 0
        push byte 0
        push ss
        lea ax, [bp-0x288]
        push ax
        push ss
        lea ax, [bp-0x84]
        push ax
        FCALL T_B99A_27F2                ; sorted Sound list; -1 if none
        add sp, 10
        mov si, ax
        mov al, [LIST_SELECTION]
        mov [bp-1], al
        cmp [LIST_SELECTION], si
        jl .position
        mov byte [bp-1], 0
.position:
        push byte 16
        push ss
        lea ax, [bp-0x288]
        push ax
        push ss
        lea ax, [bp-1]
        push ax
        push cs
        push cmp_s_sound
        FCALL T_B354_01C6                ; field 0: Sound (choice)
        add sp, 14
        mov ax, (31 << 8) | 1
        call du_rc                       ; row 1, column 31
        mov word [bp-4], 0
        cmp si, -1
        je .tune
        call .record
        mov al, [es:bx+0x12]
        cbw
        mov [bp-4], ax
.tune:  push byte 0
        push byte COMPRESS_TUNE_MAX
        push byte -120
        push byte 4
        push ss
        lea ax, [bp-4]
        push ax
        push cs
        push cmp_s_tune
        FCALL T_B354_03B1                ; field 1: Tune (word)
        add sp, 16
        mov al, 3
        mov bx, cmp_s_prompt
        call du_row_put
        cmp si, -1
        je .rule
        call .stereo_mark
.rule:  FCALL T_B77C_20C5                ; '=' rule on row 6
        call .soft_keys

.key:   push byte 2
        FCALL T_B060_035D                ; field editor: 0 = commit, else a key
        add sp, 2
        mov dx, ax
        or ax, ax
        jnz .pressed
        cmp si, -1                       ; commits act only on an existing sound
        je .key
        mov al, [FIELD_INDEX]
        or al, al
        jz .sound_field
        cmp al, 1
        jne .key
        call .record                     ; Tune committed
        mov al, [bp-4]
        mov [es:bx+0x12], al
        jmp .key
.sound_field:
        call .stereo_mark
        call .record
        mov al, [es:bx+0x12]
        cbw
        mov [bp-4], ax
        push byte 1
        FCALL T_B060_0AD9                ; redraw Tune
        add sp, 2
        mov al, [bp-1]
        cbw
        mov [LIST_SELECTION], ax
        jmp .key

.pressed:
        cmp ax, 0x78                     ; Soft Key 1 <Do it>
        je .do
        cmp ax, 0x79                     ; Soft Key 2 <Ply/Stp>
        je .play
        jmp .leave_test                  ; a mode key: leave with it

.do:    cmp si, -1
        je .again
        cmp word [bp-4], 0               ; "Tune must be 0 or more"
        jl .again
        call .record
        mov ax, [es:bx+0x1C]
        mov dx, [es:bx+0x1E]
        shr dx, 1
        rcr ax, 1
        or dx, dx
        jnz .long_enough
        cmp ax, COMPRESS_MIN_FRAMES
        jb .again
.long_enough:
        FCALL T_CFC6_0D93                ; stop all voices
        mov al, 7
        mov bx, cmp_s_busy
        call du_row_put
        call du_eol                      ; blank the rest of the row
        call .index
        mov [bp-2], al
        call compress_sound
        mov ax, [bp-4]
        sub ax, 120
        cmp ax, -120
        jge .new_tune
        mov ax, -120
.new_tune:
        mov [bp-4], ax
        call .record
        mov al, [bp-4]
        mov [es:bx+0x12], al
        push byte 1
        FCALL T_B060_0AD9
        add sp, 2
        call .record
        shr word [es:bx+0x1E], 1         ; Length
        rcr word [es:bx+0x1C], 1
        shr word [es:bx+0x16], 1         ; Soft st
        rcr word [es:bx+0x14], 1
        shr word [es:bx+0x1A], 1         ; Soft end
        rcr word [es:bx+0x18], 1
        FCALL T_D0C0_086F                ; rebuild the allocator: the freed half is free
        mov al, [bp-2]
        cbw
        cmp ax, [cs:zones_source]
        jne .zones_kept
        mov byte [cs:zones_valid], 0
.zones_kept:
        call .soft_keys
.again: xor dx, dx
        jmp .leave_test

.play:  cmp si, -1
        je .again
        FCALL T_CFC6_0D75                ; anything sounding?
        or ax, ax
        jz .start
        FCALL T_CFC6_0D93
        jmp .again
.start: call .index
        push ax
        FCALL T_CFC6_0CE9
        add sp, 2
        jmp .again

.leave_test:
        or dx, dx
        jnz .leave
        jmp .redraw
.leave: mov ax, dx
        pop di
        pop si
        leave
        retf

; AX = the selected sound's record index (word).
.index: mov al, [bp-1]
        cbw
        lea bx, [bp-0x84]
        add bx, ax
        mov al, [ss:bx]
        cbw
        ret

; ES:BX = the selected sound's record.  Clobbers AX, DX.
.record:
        call .index
        jmp snd_record                   ; index 0..127: MUL = IMUL

; "(ST)" or blanks after the Sound field (row 1, column 23).
.stereo_mark:
        push byte 23
        push byte 1
        call .index
        push ax
        FCALL T_B99A_16DF
        add sp, 6
        ret

.soft_keys:
        mov al, 7
        mov bx, cmp_s_keys
        jmp du_row_put

; NEAR.  AX = record index of a non-empty sound; DS = DGROUP.  Replaces each
; plane by its even samples in place: plane p's N words at base + p*N become
; floor(N/2) words at base + p*floor(N/2).  Writes never reach unread input
; (the output end base + p*floor(N/2) + (pos+c)/2 is at most the input end
; base + p*N + pos + c).  Keeps SI, DI, BP, DS.
compress_sound:
        push si
        push di
        call snd_record                  ; index 0..127: MUL = IMUL
        mov ax, [es:bx+0x1C]
        mov dx, [es:bx+0x1E]
        mov [cs:cmp_n], ax
        mov [cs:cmp_n+2], dx
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        mov [cs:cmp_src], ax
        mov [cs:cmp_src+2], dx
        mov [cs:cmp_dst], ax
        mov [cs:cmp_dst+2], dx
        mov al, [es:bx+0x13]
        and al, 1
        inc al
        mov [cs:cmp_planes], al
.plane: xor ax, ax
        mov [cs:cmp_pos], ax
        mov [cs:cmp_pos+2], ax
.chunk: mov ax, [cs:cmp_n]               ; c = min(BUF_W, N - pos)
        mov dx, [cs:cmp_n+2]
        sub ax, [cs:cmp_pos]
        sbb dx, [cs:cmp_pos+2]
        mov cx, ax
        or cx, dx
        jz .plane_done
        or dx, dx
        jnz .full
        cmp ax, BUF_W
        jbe .have
.full:  mov ax, BUF_W
.have:  mov [cs:cmp_c], ax
        mov bx, [cs:cmp_src]             ; read c words from src + pos
        mov cx, [cs:cmp_src+2]
        add bx, [cs:cmp_pos]
        adc cx, [cs:cmp_pos+2]
        mov dl, 1
        call .transfer
        push ds                          ; buffer[k] = buffer[2k], k < ceil(c/2)
        mov ax, SND_SEG
        RELOC_PREV
        mov ds, ax
        mov es, ax
        xor si, si
        xor di, di
        mov cx, [cs:cmp_c]
        inc cx
        shr cx, 1
        cld
.even:  lodsw
        stosw
        add si, 2
        loop .even
        pop ds
        mov ax, [cs:cmp_c]               ; write floor(c/2) words to dst + pos/2
        shr ax, 1
        jz .advance
        mov bx, [cs:cmp_pos]
        mov cx, [cs:cmp_pos+2]
        shr cx, 1
        rcr bx, 1
        add bx, [cs:cmp_dst]
        adc cx, [cs:cmp_dst+2]
        xor dl, dl
        call .transfer
.advance:
        mov ax, [cs:cmp_c]
        add [cs:cmp_pos], ax
        adc word [cs:cmp_pos+2], 0
        jmp .chunk
.plane_done:
        dec byte [cs:cmp_planes]
        jz .done
        mov ax, [cs:cmp_n]               ; next plane: src += N, dst += floor(N/2)
        mov dx, [cs:cmp_n+2]
        add [cs:cmp_src], ax
        adc [cs:cmp_src+2], dx
        shr dx, 1
        rcr ax, 1
        add [cs:cmp_dst], ax
        adc [cs:cmp_dst+2], dx
        jmp .plane
.done:  pop di
        pop si
        ret

; AX words between SND_SEG:0000 and wave word address CX:BX; DL = 1 read,
; 0 write.  BUSY is held across the transfer, as around every stock one.
.transfer:
        inc byte [BUSY]
        xor dh, dh
        push dx
        push byte 0
        push ax
        push cx
        push bx
        push strict word SND_SEG
        RELOC_PREV
        push byte 0
        FCALL T_CF92_000C
        add sp, 14
        dec byte [BUSY]
        ret

; PMONEY's own wording (not Vailixi's).  Sound:/Tune:/<Do it>/<Ply/Stp> are the
; stock Akai field and soft-key conventions.  The prompt rows are 40 columns.
cmp_s_title:  db "Compress Sound", 0
cmp_s_sound:  db "Sound:", 0
cmp_s_tune:   db "Tune:", 0
cmp_s_prompt: db "Do it: half the samples, same pitch.", 10, "Tune must be 0 or more (drops by 120).", 0
cmp_s_keys:   db "<Do it>   <Ply/Stp>", 0
cmp_s_busy:   db "Compressing...", 0
; compress_sound's working state, in the session pool (mute_storage.inc).
cmp_planes    equ cave_pool
cmp_c         equ cave_pool + 2
cmp_n         equ cave_pool + 4
cmp_src       equ cave_pool + 8
cmp_dst       equ cave_pool + 12
cmp_pos       equ cave_pool + 16
