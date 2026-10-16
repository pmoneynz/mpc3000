; Four mute groups, reached by Programs/Sounds -> 0.
; Uses the same complete raster font/framebuffer as the waveform view.
; Storage and voice contracts are in mute_storage.inc / mute_voice.inc.

; C887:0064 replaces CBW/DEC AX/MOV BX,AX/CMP BX,8 (seven bytes).
; EBC8's existing menu reader maps digit 0 to option 10.
mute_menu_dispatch:
        cmp al, 10
        je .mute
        cbw
        dec ax
        mov bx, ax
        cmp bx, 8
        FJMP T_C887_006B
.mute: call mute_ui
        mov dl, al
        FJMP T_C887_00F1

mute_ui:
        push bp
        push si
        push di
        push ds
        push es
        mov byte [cs:mu_focus], 1
        mov byte [cs:mu_typing], 0
        mov al, [MUTE_PAD]
        cmp al, 64
        jb .pad
        xor al, al
.pad:   mov [cs:mu_pad], al
        call mute_ui_context
        FCALL T_B1B1_004F
        call mute_ui_draw
        FCALL T_C4C8_0F5F
.key:   push 0
        FCALL T_BDE3_000E
        add sp, 2
        mov [cs:mu_key], al
        mov ax, [KEY_REPEAT]
        or ax, ax
        jnz .repeat
        inc ax
.repeat:mov [cs:mu_repeat], ax
        ; A stock program change may have arrived through MIDI while waiting.
        mov al, [MUTE_PROGRAM]
        cmp al, [cs:mu_program]
        je .dispatch
        mov byte [cs:mu_typing], 0
        call mute_ui_context
.dispatch:
        mov bl, [cs:mu_key]
        ; An Apply All prompt is open for exactly one key: read and clear it.
        xor ax, ax
        xchg ax, [cs:mu_confirm]
        or al, al
        jnz .confirm
        cmp bl, '0'
        jb .not_digit
        cmp bl, '9'
        jbe .digit
.not_digit:
        mov byte [cs:mu_typing], 0
        cmp bl, 'u'
        je .menu
        cmp bl, 'x'
        je .all
        cmp bl, '+'
        je .adjust
        cmp bl, '-'
        je .adjust
        cmp bl, '<'
        je .previous
        cmp bl, '^'
        je .previous
        cmp bl, '>'
        je .next
        cmp bl, '!'
        je .next
        cmp bl, 'D'
        je .pad_event
        cmp bl, 'N'
        je .midi_event
.cancel:
        mov si, modes
.mode:  mov al, [cs:si]
        inc si
        or al, al
        jz .redraw
        cmp al, bl
        jne .mode
        jmp .exit
.menu:  mov al, 'L'
.exit:  push ax
        FCALL T_C4C8_0409
        pop ax
        pop es
        pop ds
        pop di
        pop si
        pop bp
        ret
.previous:
        cmp byte [cs:mu_focus], 0
        je .redraw
        dec byte [cs:mu_focus]
        jmp .redraw
.next:  cmp byte [cs:mu_focus], 3
        je .redraw
        inc byte [cs:mu_focus]
        jmp .redraw
.pad_event:
        mov al, [MUTE_NOTE]
        jmp .note
.midi_event:
        mov al, [MUTE_NOTE_MIDI]
.note:  xor ah, ah
        push ax
        FCALL T_D9F2_003D
        add sp, 2
        cmp ax, 64
        jae .redraw
        mov [cs:mu_pad], al
        jmp .redraw
; Soft Key 1 only asks. Like the stock Delete Sound <DEL ALL SNDS!> prompt,
; the confirm is a different soft key from the one that opened it.
.all:   call mute_ui_selected_group
        inc ax
        mov ah, [cs:mu_program]
        mov [cs:mu_confirm], ax         ; group+1, program named by the prompt
        call mute_ui_draw               ; formats the digits and group text
        mov ax, [cs:mu_program_digits]
        mov [cs:mu_ask_program], ax
        ; Replace glyph rows 0-6 and 57-63; the fields and pad grid stay.
        xor ax, ax
        mov di, FB
        mov cx, ROW*7/2
        rep stosw
        mov di, FB+ROW*57
        mov cx, ROW*7/2
        rep stosw
        xor bx, bx
        mov si, mu_ask
        call text
        mov bx, 37
        mov si, mu_group_text
        call text
        mov ax, 57
        mov bx, 20
        mov si, mu_ask_keys
        call text
        jmp .blit
; AL = group+1, AH = prompt program. Soft Key 3 applies only while that
; program is still current; any other key cancels, and a mode key leaves.
.confirm:
        cmp bl, 'z'
        je .confirmed
        ; Pad hits and MIDI notes arrive as keys too (an external sequencer
        ; sends them continuously): they leave the prompt open.
        cmp bl, 'D'
        je .keep_prompt
        cmp bl, 'N'
        jne .cancel
.keep_prompt:
        mov [cs:mu_confirm], ax
        jmp .key
.confirmed:
        cmp ah, [cs:mu_program]
        jne .redraw
        dec ax
        mov dl, al
        mov al, ah
        call mute_apply_all
        jmp .redraw
.adjust:
        mov cx, [cs:mu_repeat]
        cmp byte [cs:mu_focus], 0
        je .program_step
        cmp byte [cs:mu_focus], 1
        je .enabled_step
        cmp byte [cs:mu_focus], 2
        je .pad_step
        call mute_ui_selected_group
        xor ah, ah
        mov bl, [cs:mu_key]
        mov cx, [cs:mu_repeat]
        mov dx, 4
        call mute_ui_step
        jmp .group_value
.program_step:
        xor ax, ax
        mov al, [cs:mu_program]
        mov dx, 23
        call mute_ui_step
        jmp .program_value
.pad_step:
        xor ax, ax
        mov al, [cs:mu_pad]
        mov dx, 63
        call mute_ui_step
        jmp .pad_value
.enabled_step:
        xor ax, ax
        cmp bl, '+'
        jne .enabled_value
        inc ax
        jmp .enabled_value
.digit: sub bl, '0'
        cmp byte [cs:mu_focus], 1
        je .enabled_digit
        cmp byte [cs:mu_focus], 3
        je .group_digit
        xor ax, ax
        cmp byte [cs:mu_typing], 1
        jne .first_digit
        mov al, [cs:mu_number]
        mov cl, 10
        mul cl
.first_digit:
        xor bh, bh
        add ax, bx
        mov [cs:mu_number], al
        xor byte [cs:mu_typing], 1
        or ax, ax
        jz .redraw
        dec ax
        cmp byte [cs:mu_focus], 0
        je .numeric_program
        cmp ax, 63
        jbe .pad_value
        mov ax, 63
.pad_value:
        mov [cs:mu_pad], al
        jmp .redraw
.numeric_program:
        cmp ax, 23
        jbe .program_value
        mov ax, 23
.program_value:
        cmp al, [cs:mu_program]
        je .redraw
        push ax
        FCALL T_CA45_0008
        add sp, 2
        call mute_ui_context
        jmp .redraw
.enabled_digit:
        cmp bl, 1
        ja .redraw
        mov al, bl
.enabled_value:
        mov dl, al
        mov al, [cs:mu_program]
        call mute_set_enabled
        jmp .redraw
.group_digit:
        cmp bl, 4
        ja .redraw
        mov al, bl
.group_value:
        mov dl, al
        xor bx, bx
        mov bl, [cs:mu_pad]
        mov bl, [cs:mu_alias+bx]
        mov al, [cs:mu_program]
        call mute_set_group
.redraw:
        call mute_ui_draw
%ifdef PROFILE_316
.blit:  call fast_blit                  ; wave.asm: T_C4C8_0F0D's LC7981 sequence
%else
.blit:  FCALL T_C4C8_0F0D
%endif
        jmp .key

; AX value in [0,DX], BL +/- and CX repeat. Saturating unsigned arithmetic.
mute_ui_step:
        cmp bl, '-'
        je .minus
        add ax, cx
        jc .maximum
        cmp ax, dx
        jbe .done
.maximum:
        mov ax, dx
        ret
.minus: sub ax, cx
        jae .done
        xor ax, ax
.done:  ret

; Refresh name and the native effective pad-to-note map. Duplicate valid
; MIDI notes are one native instrument: all aliases display/edit the first
; matching pad's group, just as D9F2:003D resolves a note to its first pad.
; Disabled/unassigned notes do not alias other disabled pads.
mute_ui_context:
        mov al, [MUTE_PROGRAM]
        mov [cs:mu_program], al
        les bx, [MUTE_RECORD]
        xor si, si
.name:  mov al, [es:bx+si]
        mov [cs:mu_name+si], al
        inc si
        cmp si, 16
        jb .name
        xor si, si
.notes: push si
        FCALL T_D9F2_000C
        add sp, 2
        mov [cs:mu_notes+si], al
        inc si
        cmp si, 64
        jb .notes
        xor si, si
.alias: mov ax, si
        mov [cs:mu_alias+si], al
        mov al, [cs:mu_notes+si]
        cmp al, 35
        jb .next
        cmp al, 98
        ja .next
        xor bx, bx
.scan:  cmp bx, si
        jae .next
        cmp al, [cs:mu_notes+bx]
        je .found
        inc bx
        jmp .scan
.found: mov [cs:mu_alias+si], bl
.next:  inc si
        cmp si, 64
        jb .alias
        ret

mute_ui_selected_group:
        xor bx, bx
        mov bl, [cs:mu_pad]
        mov bl, [cs:mu_alias+bx]
        mov al, [cs:mu_program]
        jmp mute_get_group

mute_ui_draw:
        ; Format top fields and the complete 64-pad membership overview.
        xor ax, ax
        mov al, [cs:mu_program]
        inc ax
        mov di, mu_program_digits
        mov cx, 2
        call digits
        mov al, [cs:mu_program]
        call mute_get_enabled
        mov si, mu_off
        or al, al
        jz .enable_text
        mov si, mu_on
.enable_text:
        mov ax, [cs:si]
        mov [cs:mu_enable_text], ax
        mov al, [cs:si+2]
        mov [cs:mu_enable_text+2], al
        xor ax, ax
        mov al, [cs:mu_pad]
        inc ax
        mov di, mu_pad_digits
        mov cx, 2
        call digits
        xor ax, ax
        mov al, [cs:mu_pad]
        mov bl, al
        shr al, 4
        add al, 'A'
        mov [cs:mu_bank], al
        mov al, bl
        and ax, 15
        inc ax
        mov di, mu_bank_digits
        mov cx, 2
        call digits
        xor bx, bx
        mov bl, [cs:mu_pad]
        xor ax, ax
        mov al, [cs:mu_notes+bx]
        mov di, mu_note_digits
        mov cx, 2
        call digits
        call mute_ui_selected_group
        mov word [cs:mu_group_text], 'OF'
        mov byte [cs:mu_group_text+2], 'F'
        or al, al
        jz .grid
        add al, '0'
        mov [cs:mu_group_text], al
        mov word [cs:mu_group_text+1], '  '
.grid:  xor si, si
        mov di, mu_grid+8
.cell:  mov bl, [cs:mu_alias+si]
        mov al, [cs:mu_program]
        call mute_get_group
        or al, al
        jnz .number
        mov al, '-'-'0'
.number:add al, '0'
        mov [cs:di], al
        inc di
        inc si
        test si, 3
        jnz .next_cell
        inc di
        test si, 15
        jnz .next_cell
        add di, 8
.next_cell:
        cmp si, 64
        jb .cell
        push ds
        pop es
        mov di, FB
        xor ax, ax
        mov cx, ROW*64/2
        rep stosw
        mov di, mu_texts                ; glyph row, cell column, string
.text:  mov ax, [cs:di]
        mov bl, ah
        xor bh, bh
        xor ah, ah
        mov si, [cs:di+2]
        push di
        call text
        pop di
        add di, 4
        cmp di, mu_texts_end
        jb .text
        ; The selected pad is also highlighted in the membership overview.
        xor ax, ax
        mov al, [cs:mu_pad]
        mov bx, ax
        and bx, 15
        mov cx, bx
        shr cx, 2
        add bx, cx
        add bx, 8
        imul bx, bx, 6
        shr ax, 4
        shl ax, 3
        add ax, 24
        mov cx, 6
        mov dx, 7
        call invert
        xor bx, bx
        mov bl, [cs:mu_focus]
        shl bx, 1
        mov ax, [cs:mu_focus_rows+bx]
        mov cx, [cs:mu_focus_widths+bx]
        mov bx, [cs:mu_focus_cols+bx]
        mov dx, 7
        jmp invert

mu_texts: db 0, 0
        dw mu_title
        db 0, 13
        dw mu_name
        db 8, 0
        dw mu_line1
        db 8, 30
        dw mu_note
        db 16, 0
        dw mu_line2
        db 24, 0
        dw mu_grid
        db 32, 0
        dw mu_grid+28
        db 40, 0
        dw mu_grid+56
        db 48, 0
        dw mu_grid+84
        db 57, 0
        dw mu_apply
        db 57, 34
        dw s_exit
mu_texts_end:
mu_title: db 'Mute Groups:',0
%ifdef PROFILE_316
mu_name  equ cave_pool                  ; session pool (mute_storage.inc)
%else
mu_name: times 17 db 0
%endif
mu_line1: db 'Program:'
mu_program_digits: db '01    Enabled:'
mu_enable_text: db 'OFF',0
mu_note: db 'Note:'
mu_note_digits: db '35',0
mu_line2: db 'Pad:'
mu_pad_digits: db '01 ('
mu_bank: db 'A'
mu_bank_digits: db '01)  Group:'
mu_group_text: db 'OFF',0
mu_grid: db 'A 01-16:---- ---- ---- ----',0
         db 'B 17-32:---- ---- ---- ----',0
         db 'C 33-48:---- ---- ---- ----',0
         db 'D 49-64:---- ---- ---- ----',0
mu_apply: db '<Apply All>',0
mu_ask: db 'Program '
mu_ask_program: db '01: set all 64 pads to group ',0  ; + mu_group_text
mu_ask_keys: db '<Do it>     <Cancel>',0  ; Soft Keys 3 and 4
mu_off: db 'OFF'
mu_on: db 'ON '
mu_focus_rows: dw 8,8,16,16
mu_focus_cols: dw 8*6,22*6,4*6,20*6
mu_focus_widths: dw 12,18,12,18
mu_program: db 0
mu_pad: db 0
mu_focus: db 0
mu_typing: db 0
mu_number: db 0
mu_key: db 0
align 2
mu_repeat: dw 1
mu_confirm: dw 0                        ; nonzero only for the key after Apply All
%ifdef PROFILE_316
mu_notes equ cave_pool + 17
mu_alias equ cave_pool + 81
%else
mu_notes: times 64 db 0
mu_alias: times 64 db 0
%endif
