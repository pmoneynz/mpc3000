; Stock Edit Sound audition. Same entry CS:IP in both supported captures.
; CFC6:0CE9(index) consumes the sound record's bounds synchronously.
; CFC6:0D75 reports any active voice; CFC6:0D93 is stock Ply/Stp's stop.
; See notes/wave_playback.md for ABI evidence and remaining hardware scope.

; Toggle audition of the highlighted, visible part of the selected pair.
; Full view: the whole selected Trim/Zone range. Fine: intersect with window.
; Preserve all caller registers and segment registers.
audition:
        pusha
        push ds
        push es
        mov byte [cs:aud_too_short], 0
        FCALL T_CFC6_0D75
        or ax, ax
        jz .start
        FCALL T_CFC6_0D93
        jmp .done
.start: mov al, [cs:sel]
        and al, 2
        call point
        mov [cs:aud_start], ax
        mov [cs:aud_start+2], dx
        mov al, [cs:sel]
        or al, 1
        call point
        mov [cs:aud_end], ax
        mov [cs:aud_end+2], dx
        ; No empty/reversed or out-of-bounds range reaches the player.
        cmp dx, [cs:len+2]
        ja .done
        jb .window
        cmp ax, [cs:len]
        ja .done
.window:
        cmp byte [cs:fine], 0
        je .ordered
        xor cx, cx
        call bound
        or dx, dx                      ; negative window start contributes 0
        js .window_end
        cmp dx, [cs:aud_start+2]
        jb .window_end
        ja .set_start
        cmp ax, [cs:aud_start]
        jbe .window_end
.set_start:
        mov [cs:aud_start], ax
        mov [cs:aud_start+2], dx
.window_end:
        mov cx, COLS
        call bound
        or dx, dx
        js .done
        cmp dx, [cs:aud_end+2]
        ja .ordered
        jb .set_end
        cmp ax, [cs:aud_end]
        jae .ordered
.set_end:
        mov [cs:aud_end], ax
        mov [cs:aud_end+2], dx
.ordered:
        mov ax, [cs:aud_end]
        mov dx, [cs:aud_end+2]
        cmp dx, [cs:aud_start+2]
        jb .done
        ja .bounds
        cmp ax, [cs:aud_start]
        jbe .done
.bounds:
        ; The playback task must not start a sequenced voice of this sound
        ; while its record holds the audition range: hold the playback lock
        ; (its tick only tests BUSY at entry, so the call below cannot wait on it).
        inc byte [BUSY]
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        mov si, [cs:rec]
        mov ax, [es:si+0x14]
        mov dx, [es:si+0x16]
        mov [cs:aud_saved_start], ax
        mov [cs:aud_saved_start+2], dx
        mov ax, [es:si+0x18]
        mov dx, [es:si+0x1A]
        mov [cs:aud_saved_end], ax
        mov [cs:aud_saved_end+2], dx
        mov ax, [cs:aud_start]
        mov dx, [cs:aud_start+2]
        mov [es:si+0x14], ax
        mov [es:si+0x16], dx
        mov ax, [cs:aud_end]
        mov dx, [cs:aud_end+2]
        mov [es:si+0x18], ax
        mov [es:si+0x1A], dx
        push word [cs:sound_index]
        FCALL T_CFC6_0CE9
.return_from_stock:
        add sp, 2
        ; Stock calls may change ES; always re-establish the record pointer.
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        mov si, [cs:rec]
        mov ax, [cs:aud_saved_start]
        mov dx, [cs:aud_saved_start+2]
        mov [es:si+0x14], ax
        mov [es:si+0x16], dx
        mov ax, [cs:aud_saved_end]
        mov dx, [cs:aud_saved_end+2]
        mov [es:si+0x18], ax
        mov [es:si+0x1A], dx
        dec byte [BUSY]
.done:  pop es
        pop ds
        popa
        ret

; These two stock-player hooks apply only to our exact call chain:
; CFC6:039E <- CFC6:0D70 (CE9) <- F07D:audition.return_from_stock.
; No global active flag or active-voice scan can capture another task's note.
; Preserve every register; return ZF=1 only for that chain.
audition_callsite:
        push bx
        push si
        cmp word [ss:bp+2], PLAYER_CE9_RET
        jne .done
        cmp word [ss:bp+4], strict word PLAYER_SEG
        RELOC_PREV
        jne .done
        mov bx, [ss:bp]
        cmp word [ss:bx+2], audition.return_from_stock
        jne .done
        mov si, cs
        cmp [ss:bx+4], si
.done:  pop si
        pop bx
        ret

; CFC6:069D originally subtracts 30 ms from DX:AX. Keep the original
; arithmetic for all other callers. Our timer still rounds down to 10 ms;
; do not extend the source end or the playback deadline past the selection.
audition_duration:
        call audition_callsite
        je .ours
        sub ax, 30
        sbb dx, 0
        jmp .return
.ours:  or dx, dx
        jnz .return
        or ax, ax
        jnz .return
        mov byte [cs:aud_too_short], 1
        FJMP T_CFC6_0B21
.return:
        FJMP T_CFC6_06A3

; CFC6:0897 receives the pitch-adjusted, floored natural-stop tick count.
; One tick can expire almost immediately at the next shared timer phase.
; Reject fewer than two ticks before any voice is allocated or started.
; The stock frame's epilogue restores DI, SI, BP and returns to CE9.
audition_ticks:
        call audition_callsite
        jne .stock
        cmp ax, 2
        jae .stock
        mov byte [cs:aud_too_short], 1
        FJMP T_CFC6_0B21
.stock: mov [bp-0x58], ax
        cmp word [bp-0x58], 0
        FJMP T_CFC6_089E

align 2
sound_index: dw 0
aud_start: dd 0
aud_end: dd 0
aud_saved_start: dd 0
aud_saved_end: dd 0
aud_too_short: db 0
