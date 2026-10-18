; Stock Edit Sound numeric entry for the waveform view.
;
; stock_numeric(BL = first digit, or 0 to open without a digit)
;   DS       = 8010 (DGROUP)
;   page_bp  = BP of the suspended B99A Edit Sound page frame
;   sel      = selected waveform point (0..3)
;
; Before the waveform first enters graphics mode, the caller must save the
; Edit Sound character shadow with B1B1:004F.  This routine returns to text
; mode, restores that shadow with B1B1:0055, refreshes the live stock fields,
; and runs a bounded loop made from the stock numeric-editor primitives.  A
; digit already read by the graphics loop is that loop's first key, ahead of
; anything still in the stock key queue.
;
; AX = 0 for a normal return to the waveform. Up from an End component
; commits the entry and returns '^' for the waveform's zone shortcut.
; A mode-key code is returned
; unchanged so the caller can leave the page and let the OS switch modes.
; All other passed keys cancel the numeric entry and are consumed.
;
; The stock editor owns three separate fields for each point: seconds,
; milliseconds, and samples.  B060:006B/:021C select and initialize a real
; field; B31B:0007 parses and edits it; B060:0715 commits its entry buffer.
; The wrapper handles B31B's 0400h/0800h previous/next actions itself, so
; navigation cannot escape the selected point's three-field value.
; NUM_EDITING (profile.inc) is 0 while an entry buffer is active.

stock_numeric:
        push bp
        mov bp, sp
        push bx
        push cx
        push dx
        push si
        push di
        push ds
        push es
        mov [cs:numeric_first], bl
        mov al, [cs:sel]
        mov [cs:numeric_sel], al

        ; C4C8:0409 leaves graphics mode and clears the LCD.  INT 43 AX=6,
        ; through B1B1:0055, replays the Edit Sound shadow saved at entry.
        FCALL T_C4C8_0409
        FCALL T_B1B1_0055
        call numeric_sync_all

        mov al, [cs:numeric_sel]
        call numeric_field_base
        mov [cs:numeric_base], al
        mov [cs:numeric_field], al
        call numeric_select_field

.input:
        ; Match B060's numeric cursor: shape 3 before entry, 2 while typing.
        mov ax, 3
        cmp byte [NUM_EDITING], 0
        jne .cursor
        dec ax
.cursor:
        push ax
        FCALL T_B1B1_0008
        add sp, 2
        ; The graphics loop has already read the first digit through
        ; BDE3:000E.  Dispatch it as this pass's key instead of queueing it:
        ; D6E0:0075 appends at the FIFO tail, behind any key typed during the
        ; mode switch and redraw above.  BL=0 (Enter) reads normally and so
        ; opens the seconds field without input.
        mov al, [cs:numeric_first]
        mov byte [cs:numeric_first], 0
        or al, al
        jnz .have_key
        push 0
        FCALL T_BDE3_000E               ; normalized key after global filter
        add sp, 2
.have_key:
        mov [cs:numeric_key], al
        push 0
        FCALL T_B1B1_0008               ; hide the cursor while dispatching
        add sp, 2

        mov al, [cs:numeric_key]
        cmp al, 0x0D
        je .enter
        cmp al, '^'
        jne .edit
        test byte [cs:numeric_sel], 1
        jnz .zone
.edit:
        mov dl, [NUM_EDITING]
        mov [cs:numeric_was_editing], dl
        xor ah, ah
        push 0                          ; B31B flags: do not accept pad events
        push ax
        FCALL T_B31B_0007
        add sp, 4
        mov [cs:numeric_result], ax
        or ax, ax
        jz .input                       ; digit/backspace/consumed event
        cmp ax, 0x8000
        je .changed                     ; +/- (or another immediate write)
        mov dx, ax
        and dx, 0x0F00
        cmp dx, 0x0400
        je .previous
        cmp dx, 0x0800
        je .next
        cmp al, '^'                     ; keep Up/Down inside this triple
        je .input
        cmp al, '!'
        je .input
        jmp .passed

.enter:
        mov al, [NUM_EDITING]
        mov [cs:numeric_was_editing], al
        FCALL T_B060_0715
        cmp byte [cs:numeric_was_editing], 0
        jne .normal                     ; idle Enter changes no frame value
        call numeric_commit
        jmp .normal

.zone:
        ; Treat Up as accepting this End value before selecting its zone.
        ; Idle Up must preserve frame values that the stock display rounds.
        mov al, [NUM_EDITING]
        mov [cs:numeric_was_editing], al
        FCALL T_B060_0715
        cmp byte [cs:numeric_was_editing], 0
        jne .zone_graphics
        call numeric_commit
.zone_graphics:
        call refresh
        FCALL T_C4C8_0F5F
        mov ax, '^'
        jmp .return

.previous:
        mov al, [cs:numeric_field]
        cmp al, [cs:numeric_base]
        jbe .input                       ; bound Left at seconds
        dec byte [cs:numeric_field]
        call numeric_select_field
        jmp .input

.next:
        ; A typed Right (or decimal navigation) has already committed the
        ; component through B060:0715.  Idle Right only navigates and must not
        ; convert a redraw-clamped 44-sample component back into the frame.
        cmp byte [cs:numeric_was_editing], 0
        jne .advance
        call numeric_commit
.advance:
        mov al, [cs:numeric_field]
        sub al, [cs:numeric_base]
        cmp al, 2
        jae .normal                     ; Right past samples closes the dialog
        inc byte [cs:numeric_field]
        call numeric_select_field
        jmp .input

.changed:
        call numeric_commit
        jmp .normal

.passed:
        call numeric_sync_all           ; discard any uncommitted draft
        mov ax, [cs:numeric_result]
        mov si, numeric_mode_keys
.mode: mov dl, [cs:si]
        or dl, dl
        jz .normal
        inc si
        cmp al, dl
        jne .mode
        jmp .return                     ; let the caller pass the mode key

.normal:
        call refresh
        FCALL T_C4C8_0F5F               ; return to graphics and blit
        xor ax, ax                      ; graphics calls do not define AX
.return:
        mov dl, [cs:numeric_sel]
        mov [cs:sel], dl
        mov [cs:numeric_result], ax
        pop es
        pop ds
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        pop bp
        mov ax, [cs:numeric_result]
        ret

; AL point -> AL first field in its stock three-field time value.
; 0 soft start -> 1, 1 soft end -> 7, 2 zone start -> 4, 3 zone end -> 10.
numeric_field_base:
        xor ah, ah
        mov si, ax
        mov al, [cs:numeric_field_bases+si]
        ret

; Select numeric_field in the live B99A field list and initialize its stock
; parser/display state.  The records still point into the suspended page.
numeric_select_field:
        xor ah, ah
        mov al, [cs:numeric_field]
        push ax
        FCALL T_B060_006B
        add sp, 2
        FCALL T_B060_021C
        ret

; Convert all four live frame positions back into the suspended B99A page's
; component triples, then ask the stock page to redraw all 17 field records.
; Triple layout is samples at +0, milliseconds at +2, seconds at +4.
numeric_sync_all:
        xor al, al                       ; soft start -> page BP-18h
        call point
        mov bx, [cs:page_bp]
        sub bx, 0x18
        call numeric_store_components

        mov al, 1                       ; soft end -> page BP-1Eh
        call point
        mov bx, [cs:page_bp]
        sub bx, 0x1E
        call numeric_store_components

        mov al, 2                       ; zone start -> page BP-0Ch
        call point
        mov bx, [cs:page_bp]
        sub bx, 0x0C
        call numeric_store_components

        mov al, 3                       ; zone end -> page BP-12h
        call point
        mov bx, [cs:page_bp]
        sub bx, 0x12
        call numeric_store_components

        FCALL T_B99A_16BB
        ret

; Store DX:AX frames as stock components at SS:BX.
numeric_store_components:
        push dx                         ; dword high, dword low
        push ax
        push ss                         ; far destination segment, offset
        push bx
        FCALL T_B99A_266D
        add sp, 8
        ret

; Convert the selected component triple to frames and move the real point by
; desired-current.  move supplies the existing pair and sound-length clamps.
; Resynchronizing afterward also reflects any clamp in the stock text fields.
numeric_commit:
        mov al, [cs:numeric_sel]
        call point
        mov [cs:numeric_current], ax
        mov [cs:numeric_current+2], dx

        mov bx, [cs:page_bp]
        mov al, [cs:numeric_sel]
        cmp al, 0
        je .soft_start
        cmp al, 1
        je .soft_end
        cmp al, 2
        je .zone_start
        sub bx, 0x12                    ; zone end
        jmp .convert
.soft_start:
        sub bx, 0x18
        jmp .convert
.soft_end:
        sub bx, 0x1E
        jmp .convert
.zone_start:
        sub bx, 0x0C
.convert:
        push ss
        push bx
        FCALL T_B99A_2619
        add sp, 4
        sub ax, [cs:numeric_current]
        sbb dx, [cs:numeric_current+2]
        mov bl, [cs:numeric_sel]
        mov [cs:sel], bl
%ifdef PROFILE_316
        mov byte [cs:lc_commit], 1      ; a committed value: Lazy Chop's snap applies
        call move
        mov byte [cs:lc_commit], 0
%else
        call move
%endif
        call numeric_sync_all
        ret

numeric_field_bases: db 1, 7, 4, 10
%ifdef PROFILE_316
numeric_mode_keys    equ modes                 ; the same mode-key list (wave.asm)
%else
numeric_mode_keys:   db "LMFJGUSlsOK", 0
%endif
numeric_first:       db 0
numeric_sel:         db 0
numeric_base:        db 0
numeric_field:       db 0
numeric_key:         db 0
numeric_was_editing: db 0
align 2
numeric_current:     dd 0
numeric_result:      dw 0
