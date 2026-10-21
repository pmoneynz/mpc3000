; OS 3.16: Track Mute.  Press SONG on the Song page: a 4 x 4 page of the
; active sequence's tracks, one per pad, where a pad hit mutes or unmutes its
; track (the stock Play/Record "On:" flag) while the sequence plays.  PMONEY's
; own version of the Track Mute page of the third-party OS 3.39.3; its
; behaviour, not its code (notes/track_mute.md).  Unlike 3.39.3 it keeps the
; stock Song page and Help, maps tracks to sequence slots as Play/Record does,
; reads the pad from the panel parser (Lazy Chop's pad ring) instead of
; [D399], and writes each change through to the track record.
;
;   pads          mute / unmute tracks bank+1 .. bank+16; the pads do not
;                 sound or record while the page is open (Lazy Chop's pad
;                 ownership, pad_own_press, with MODE TM_MODE)
;   PAD BANK      tracks 1-16, 17-32, 33-48, 49-64
;   Soft Key 1    <All on>: unmute tracks 1-99
;   PLAY / START  play the active sequence; the page stays (xp_play_stay)
;   SONG          back to the Song page; MAIN SCREEN and the other mode keys
;                 leave as usual
;
; Hooks (WAVE316.args), DS = DGROUP: 0x15BD7, the mode dispatcher's 'G' case,
; CALLF to the stock Song page 0671:000A, now CALLF tm_song; 0x69E3, the Song
; page's SONG key (tm_song_key).

TM_CELLS    equ 16
TM_MODE     equ 'O'         ; the page runs as the Other page's mode

; FAR, in place of the stock Song page (no arguments, AX = the key that left
; it).  SONG on the Song page opens Track Mute; SONG there opens the Song page.
tm_song:
        cmp byte [cs:tm_next], 0
        jne .mute
        FCALL T_B3FD_0006               ; the stock Song page (tm_song_key sets
        retf                            ; tm_next; its other 'G' returns, the
                                        ; <Ins/Del> and Convert refreshes, do not)
.mute:  mov byte [cs:tm_next], 0
        call tm_page
        cbw
        retf

; JMP from 0671:02D3 (image 0x69E3), the Song page's key loop after 02D7:0357
; (AX = key).  Stock skips SONG here (CMP AX,'G' / JNZ / JMP 0F6F: the page
; stays); now SONG leaves the page with 'G', its frame's exit flag [bp-4] set,
; and tm_song opens Track Mute.
tm_song_key:
        cmp ax, 'G'
        jne .other
        mov word [bp-4], 1
        mov byte [cs:tm_next], 1        ; the next 'G' dispatch is Track Mute
        FJMP T_B3FD_085B                ; the loop's exit test: return [bp-2] = 'G'
.other: FJMP T_B3FD_02D7                ; the next key compare (CMP AX,50h)

; JMP from pad_own_press (lazychop316.inc) while the page is open: with MODE
; TM_MODE (belt and braces, as Lazy Chop's MODE 'L' test) the hit goes to Lazy
; Chop's cave ring and key 'D' instead of ring 5, so the pad neither sounds nor
; records; otherwise stock.
tm_pad_press:
        cmp byte [MODE], TM_MODE
        jne pad_own_stock
        push si
        FCALL T_D52A_0190               ; DX:AX = TCT0 time (BX, CX change)
        jmp lc_isr_stamped

; Near.  The page; AL = the key that leaves it.  Keeps SI, DI, BP.
tm_page:
        push si
        push di
        cmp byte [SONG_LOADED], 0       ; the Song page loaded the song into the
        je .seq                         ; header (3C97:0009 sets [86DA]): leave it
        FCALL T_E704_0081               ; as the dispatcher does before Play/Record
.seq:   mov byte [MODE], TM_MODE        ; PLAY plays the active sequence (only
        mov byte [XP_PLAY_SCREEN], 'M'  ; 'G' plays the song, 3481:0215), and the
                                        ; play-screen updater (40B8 region, image
                                        ; 0x40BB0: modes M, G, S, '/') leaves the
                                        ; page alone.  [D39C] = Play/Record, as
                                        ; 148A:0022 sets it; the Song page set 'G'.
                                        ; The dispatcher sets MODE on the way out
                                        ; and the Song page [D39C] on its entry.
        cli
        mov al, [cs:lc_tail]            ; hits from before the page are dropped
        mov [cs:lc_head], al
        mov byte [cs:tm_owned], 1
        sti
.draw:  mov bx, tm_s_title
        call du_title
        mov bx, tm_s_keys
        call du_keys
        mov byte [cs:tm_bank], 0xFF
.loop:  mov al, [LC_BANK]
        and al, 0x30
        cmp al, [cs:tm_bank]
        je .ring
        mov [cs:tm_bank], al
        call tm_grid
.ring:  call lc_pop                     ; CL = pad + bank
        jc .key
        call tm_toggle
        jmp .ring
.key:   call lc_err_box                 ; BDE3:000E's error box, pads stock
        jne .take
        mov byte [cs:tm_owned], 0
        push 0
        FCALL T_BDE3_000E
        add sp, 2
        mov byte [cs:tm_owned], 1
        push ax
        call .redraw
        pop ax
        jmp .dispatch
.take:  call lc_take_key                ; AL = a key, 0 = none
        or al, al
        jz .loop
.dispatch:
        cmp al, 'x'                     ; Soft Key 1 <All on>
        jne .mode
        call tm_all_on
        mov byte [cs:tm_bank], 0xFF
        jmp .loop
.mode:  mov si, modes                   ; SONG ('G'), MAIN SCREEN and the
.m:     mov ah, [cs:si]                 ; other mode keys leave
        inc si
        or ah, ah
        jz .loop                        ; anything else, pads ('D') included
        cmp ah, al
        jne .m
        mov byte [cs:tm_owned], 0
        pop di
        pop si
        ret
.redraw:
        mov bx, tm_s_title
        call du_title
        mov bx, tm_s_keys
        call du_keys
        mov byte [cs:tm_bank], 0xFF
        ret

; CL = track - 1 (0..63): mute <-> unmute, store it, redraw the cell.
tm_toggle:
        xor ch, ch
        mov di, cx
        inc di                          ; DI = track
        call tm_slot
        jc .r
        xor byte [bx+TRK_FLAGS], 1      ; bit 0 set = muted (stock "On:NO")
        call tm_store
        mov ax, di
        dec ax
        and al, 0x30
        cmp al, [cs:tm_bank]
        jne .r
        mov ax, di
        call tm_cell
.r:     ret

; <All on>: unmute tracks 1-99 of the active sequence.
tm_all_on:
        mov di, 1
.t:     call tm_slot
        jc .next
        test byte [bx+TRK_FLAGS], 1
        jz .next
        and byte [bx+TRK_FLAGS], 0xFE
        call tm_store
.next:  inc di
        cmp di, 99
        jbe .t
        ret

; DI = track 1..99: BX = its slot, as Play/Record maps it (148A:0C6E,
; image 0x1552A, rebuilding a missing map first).  CF = 1: no slot.
tm_slot:
        mov bl, [di+TRK_MAP]
        cmp bl, 0xFF
        jne .ok
        push ds
        push SEQ_HDR
        FCALL T_E291_0376
        add sp, 4
        mov bl, [di+TRK_MAP]
        cmp bl, 0xFF
        jne .ok
        stc
        ret
.ok:    xor bh, bh
        clc
        ret

; BX = slot: copy its header flags to its track record, as 148A:11BC does for
; the current track (without touching the current track or [8976], which the
; playback task reads).  Changes AX, CX, DX, flags.
tm_store:
        push es
        push si
        les si, [SEQ_PTR]
        mov ax, es
        or ax, si
        jz .r
        mov cl, [es:si+0x150]           ; track records
        xor ch, ch
        add si, 0x151
        jcxz .r
.rec:   cmp [es:si], bl
        je .found
        add si, 0x18
        loop .rec
        jmp .r
.found: mov al, [bx+TRK_FLAGS]
        mov [es:si+2], al
.r:     pop si
        pop es
        ret

; The 16 cells of the shown bank, pads 13-16 on top as on the panel, and row 5.
tm_grid:
        push di
        mov di, 1
.c:     mov al, [cs:tm_bank]
        xor ah, ah
        add ax, di
        call tm_cell
        inc di
        cmp di, TM_CELLS
        jbe .c
        mov al, 5
        call du_at
        mov bx, tm_s_seq
        call du_put
        mov al, [ACTIVE_SEQ]
        call tm_two
        mov bx, tm_s_bank
        call du_put
        mov al, [cs:tm_bank]
        shr al, 4
        add al, 'A'
        mov [cs:tm_s_bankid], al
        mov bx, tm_s_bankid
        call du_put
        mov al, [cs:tm_bank]
        inc ax
        call tm_two
        mov bx, tm_s_to
        call du_put
        mov al, [cs:tm_bank]
        add al, TM_CELLS
        call tm_two
        call du_eol
        pop di
        ret

; AX = track 1..64: its cell.  "NN NAME   " on, "NN(muted) " muted,
; "NN -      " for an empty track.  Keeps DI.
tm_cell:
        push di
        push si
        mov di, ax
        dec ax
        and ax, 15
        mov cl, al
        mov al, 4                       ; row 4 - (pad / 4), column 10 * (pad % 4)
        mov ah, cl
        shr ah, 2
        sub al, ah
        and cl, 3
        mov ah, cl
        shl ah, 1
        shl ah, 1
        add ah, cl
        shl ah, 1
        call du_rc
        mov ax, di
        call tm_two
        mov si, tm_cellbuf
        mov word [cs:si], '  '
        mov word [cs:si+2], '  '
        mov word [cs:si+4], '  '
        mov word [cs:si+6], '  '
        call tm_slot
        jc .empty
        test byte [bx+TRK_FLAGS], 1
        jz .on
        mov bx, tm_s_muted
        call du_put
        jmp .r
.on:    push cs
        push tm_name
        push bx
        mov al, [ACTIVE_SEQ]
        cbw
        push ax
        FCALL T_E4D6_000D               ; (seq, slot, buffer): 0 = named
        add sp, 8
        or ax, ax
        jnz .empty
        mov bx, 0
.copy:  mov al, [cs:tm_name+bx]
        or al, al
        jz .put
        mov [cs:si+bx+1], al
        inc bx
        cmp bx, 6
        jb .copy
        jmp .put
.empty: mov byte [cs:si+1], '-'
.put:   mov byte [cs:si+8], 0
        mov bx, si
        call du_put
.r:     pop si
        pop di
        ret

; AL = 0..99: two digits at the cursor.  Changes AX, BX.
tm_two:
        xor ah, ah
        mov bl, 10
        div bl
        add ax, '00'
        mov [cs:tm_digits], ax
        mov bx, tm_digits
        jmp du_put

tm_next:     db 0               ; 1: SONG was pressed on the Song page
tm_owned:    db 0               ; the page owns the pads (with MODE TM_MODE)
tm_bank:     db 0               ; bank shown (00/10/20/30h), FFh = redraw
tm_digits:   db "00", 0
tm_cellbuf:  times 9 db 0
tm_name:     times 24 db 0      ; E4D6:000D writes at least 17 bytes
tm_s_bankid: db "A: ", 0
; Screen text is PMONEY's own.
tm_s_title:  db "Track Mute", 0
tm_s_keys:   db "<All on>", 0
tm_s_muted:  db "(muted) ", 0
tm_s_seq:    db "Seq ", 0
tm_s_bank:   db "  Pads mute tracks, bank ", 0
tm_s_to:     db "-", 0
