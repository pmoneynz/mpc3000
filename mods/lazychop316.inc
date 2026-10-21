; Lazy Chop for PMONEY on OS 3.16 (PROFILE_316 only).  Specification, owner
; rules R1-R4 and decisions D1-D10: notes/lazy_chop.md; what was built, with its
; evidence tags: its "Implementation" section.  3.16 relative seg:off addresses
; (image offset seg*16+off); hooks in mods/WAVE316.args.
;
; Pad ownership (spec section 4).  Two hooks in the panel parser 2B6D:0109 (the
; serial ISR 2B6D:006B calls it, IF = 0, DS = DGROUP, ISR stack):
;   2B6D:022E (image 0x2B8FE) pad_own_press: a pad press, about to queue its
;             4-byte event in ring 5.  Owned: timestamp, the cave ring, key 'D';
;             ring 5 is skipped (rejoin 2B6D:0255).  Otherwise the replaced
;             MOV BX,6ACh / MOV CL,[7018h] and the stock queue (2B6D:0235).
;   2B6D:04A5 (image 0x2BB75) pad_own_release: a pad release (its only entry,
;             2B6D:01A2; state 025B, the other JMP 04A5 at 025E, has no writer).
;             A release of a raw pad captured while owned is skipped (2B6D:04C3);
;             every other release reaches stock (2B6D:04AC), so a pad held across
;             the view's entry releases normally and [9447] stays exact.
; Owned = lc_owned (set only inside the wave view, cleared on its every exit)
; and MODE 'L' and OPTION 6 (belt and braces: a stuck flag cannot silence the
; pads outside Edit Sound), or tm_owned (the Track Mute page) and its MODE (trackmute316.inc).  MIDI notes are not owned (D8).
;
; Playback: aud_range (wave_playback.inc) is the one audition entry; the take,
; the pads and Ply/Stp all reach CFC6:0CE9 from it.  Mono retrigger (D5) stops
; only the channels captured from that call chain (lc_capture, from
; mute_voice_alloc_wrapper's unmapped branch while the view owns the pads),
; with the one-channel stop T_D21F_0008, never the global CFC6:0D93.

LC_RING         equ 16          ; cave ring entries, 8 bytes: time dword, slot, velocity
LC_MAX          equ 64          ; slices (R3: banks A-D)
LC_MIN          equ CHOP_MIN_FRAMES ; 1368 (wave_chop.inc): minimum slice, frames: the shortest Sound stock 3.16
                                ; keys on (20ED:0697..06C0: floor(10 * (end - start
                                ; - skip) / 441) ms - 30 must be > 0; skip = 0 for a new
                                ; program's notes), so every slice that auditions in the
                                ; view also plays after Convert
LC_SNAP_W       equ 88          ; snap window, frames either side (2 ms at 44.1 kHz)
LC_OFFSET_MAX   equ 20          ; user offset, ms
LC_K_LAT        equ 0           ; D9: latency constant in TCT0 counts (0 in MAME builds)
LC_COUNTS_MS    equ 2000        ; TCT0 counts per ms (0.5 us units, 2B50:0194)
LC_FIND_NONE    equ 0xFD00      ; find first / next: no (more) file (MAME: an empty SCSI
                                ; partition, the end of a floppy's list; no floppy: FF80h)
LC_DISK_N       equ 1000        ; slice numbers checked against the disk (3 digits)
LC_OWNER_AUD    equ 0x62        ; owner note of a CFC6:0CE9 voice (20ED:0D70 PUSH 62h)

; ---------------------------------------------------------------- ISR hooks

; JMPF from 2B6D:022E.  AL, BL, CL are the parser's (free here: the replaced
; bytes set BX and CL).  Owned path: AX, BX, CX, DX change, as the stock queue
; calls do; SI, DI, ES are kept.
pad_own_stock equ pad_own_press.stock   ; Track Mute's way back to the stock queue
pad_own_press:
        cmp byte [cs:lc_owned], 0
        jne .check
        cmp byte [cs:tm_owned], 0       ; Track Mute (trackmute316.inc)
        jne tm_pad_press
.stock: mov bx, 0x06AC                  ; the replaced bytes
        mov cl, [PANEL_STATUS]
        FJMP T_D547_0231
.check: cmp byte [MODE], 'L'
        jne .stock
        cmp byte [OPTION], 6
        jne .stock
        push si
        FCALL T_D52A_0190               ; DX:AX = TCT0 time (BX, CX change)
lc_isr_stamped:
        mov bl, [cs:lc_tail]
        mov bh, bl
        inc bh
        and bh, LC_RING - 1
        cmp bh, [cs:lc_head]
        je .full
        mov si, bx
        and si, 0x00FF
        shl si, 3
        mov [cs:lc_ring+si], ax
        mov [cs:lc_ring+si+2], dx
        mov al, [LC_PAD_RAW]            ; slot = pad + bank, from the parser's own bytes
        add al, [LC_BANK]               ; (as 2B6D:0155..015C; [D399] is also written by
        mov [cs:lc_ring+si+4], al       ; the task-side MIDI note handler 307E:0093)
        mov al, [LC_PAD_VEL]
        mov [cs:lc_ring+si+5], al
        mov [cs:lc_tail], bh            ; publish after the entry is complete
        mov bx, KEY_QUEUE
        mov cl, 'D'                     ; as the stock UI callback 2CFF:0037 queues it
        FCALL T_DA09_0000               ; a full key queue loses the key, not the hit
        jmp .captured
.full:  inc byte [cs:lc_dropped]
.captured:
        mov cl, [LC_PAD_RAW]
        and cl, 15
        mov ax, 1
        shl ax, cl
        or [cs:lc_captured], ax         ; its release stays in the cave
        pop si
        FJMP T_D547_0251

; JMPF from 2B6D:04A5.  AX and CL are free (the replaced bytes and the stock
; queue calls set them).
pad_own_release:
        mov cl, [LC_PAD_RAW]
        and cl, 15
        mov ax, 1
        shl ax, cl
        test [cs:lc_captured], ax
        jnz .owned
        mov bx, 0x06AC                  ; the replaced bytes
        mov cl, [PANEL_STATUS]
        FJMP T_D547_04B6
.owned: not ax
        and [cs:lc_captured], ax
        FJMP T_D547_04CD

; JMPF from 2B6D:02CC (pad pressure, after the note is known): the stock stores
; the pressure in the held table [9548 + note] (MOV [BX-6AB8h],AL) that the
; punch-in and pad code read as "held" (32AD:0009, 308E:000A).  For a pad captured
; while owned the store is skipped; any other pad is stock.  BX = note, AL = value.
pad_own_pressure:
        push ax
        push cx
        mov cl, [LC_PAD_RAW]
        and cl, 15
        mov ax, 1
        shl ax, cl
        test [cs:lc_captured], ax
        pop cx
        pop ax
        jnz .owned
        mov [bx-0x6AB8], al             ; the replaced bytes
.owned: mov bx, 0x0121
        FJMP T_D547_02CF

; ---------------------------------------------------------------- ring and time

; CF = 1: empty.  Else DX:AX = time, CL = slot, the entry consumed.  Keeps BX.
lc_pop: push bx
        mov bl, [cs:lc_head]
        cmp bl, [cs:lc_tail]
        je .empty
        xor bh, bh
        shl bx, 3
        mov ax, [cs:lc_ring+bx]
        mov dx, [cs:lc_ring+bx+2]
        mov cl, [cs:lc_ring+bx+4]
        mov bl, [cs:lc_head]            ; read the entry before freeing its slot
        inc bl
        and bl, LC_RING - 1
        mov [cs:lc_head], bl
        pop bx
        clc
        ret
.empty: pop bx
        stc
        ret

lc_flush:
        push ax
        mov al, [cs:lc_tail]
        mov [cs:lc_head], al
        pop ax
        ret

; DX:AX = TCT0 time now, task context, without 2B50:0194: its IR0-only STI
; window, taken from a task, can reschedule with the ICU mask left at FEh.  The
; same sum (base [D501] + 20000 - counter 0), read with interrupts off; a base
; that moved while interrupts were on again (a reload just before or after the
; latch, serviced in between) makes it read again.  The ICU is not touched.
; Keeps BX, CX, SI, DI.
lc_time:
        push bx
        push cx
.again: cli
        mov bx, [LC_TIME_BASE]
        mov dx, 0xC033
        xor al, al
        out dx, al                      ; latch counter 0
        mov dx, 0xC030
        in al, dx
        mov cl, al
        in al, dx
        mov ch, al
        sti
        nop
        nop
        cli
        cmp bx, [LC_TIME_BASE]
        sti
        jne .again
        mov ax, 20000
        sub ax, cx
        mov dx, [LC_TIME_BASE+2]
        add ax, bx
        adc dx, 0
        cli                             ; the high word of the same base
        cmp bx, [LC_TIME_BASE]
        sti
        jne .again
        pop cx
        pop bx
        ret

; DX:AX = time -> DX:AX = frames from t0 + K, 0 before it:
; pos = q*441 + (r*441 + 10000) div 20000, (q, r) = divmod(t - t0 - K, 20000).
; t - t0 is taken mod 2^32 (the base wraps after 35.8 min); a take is shorter
; than 2^31 counts (17.9 min).  Keeps BX, CX, SI, DI.
lc_pos: push bx
        push cx
        sub ax, [cs:lc_t0]
        sbb dx, [cs:lc_t0+2]
        sub ax, [cs:lc_k]
        sbb dx, [cs:lc_k+2]
        jns .pos
        xor ax, ax
        xor dx, dx
        jmp .r
.pos:   mov cx, 20000
        mov bx, ax
        mov ax, dx
        xor dx, dx
        div cx                          ; AX = q high word (0..3), DX = its remainder
        push ax
        mov ax, bx
        div cx                          ; AX = q low word, DX = r
        push ax
        mov ax, 441
        mul dx                          ; r * 441 < 8,820,000
        add ax, 10000
        adc dx, 0
        div cx                          ; the rounded part, 0..441
        mov bx, ax
        pop ax
        mov cx, 441
        mul cx
        add ax, bx
        adc dx, 0
        pop bx                          ; q high
        push dx
        push ax
        mov ax, 441
        mul bx                          ; q high * 441 (DX = 0)
        pop bx
        pop dx
        add dx, ax                      ; + q high * 441 * 65536
        mov ax, bx
.r:     pop cx
        pop bx
        ret

; lc_k = offset * 2000 + LC_K_LAT (signed TCT0 counts).
lc_set_k:
        mov al, [cs:lc_offset]
        cbw
        mov dx, LC_COUNTS_MS
        imul dx
        add ax, LC_K_LAT & 0xFFFF
        adc dx, LC_K_LAT >> 16
        mov [cs:lc_k], ax
        mov [cs:lc_k+2], dx
        ret

; ---------------------------------------------------------------- view lifecycle

; After zones_enter: own the pads whenever the view has a zone map (D1).
lc_enter:
        mov byte [cs:lc_phase], 0
        mov byte [cs:lc_note], 0
        mov byte [cs:lc_box], 0
        mov byte [cs:lc_ask_eq], 0
        mov byte [cs:lc_edit_dirty], 0
        call lc_flush
        mov al, [cs:zones_valid]
        mov [cs:lc_owned], al
        ret

; Every exit of the view (Exit, Help, Main Screen, a mode key).  Keeps AX.
lc_leave:
        push ax
        call lc_settle
        cmp byte [cs:lc_phase], 0
        je .own
        call lc_take_cancel
.own:   mov byte [cs:lc_owned], 0
        mov byte [cs:lc_aud_n], 0       ; the allocator wrapper stops looking (lc_alloc_seen)
        mov byte [cs:lc_box], 0
        pop ax
        ret

; SI = a status string: shown on row 49 until the next key.
lc_status:
        mov [cs:lc_note_ptr], si
        mov byte [cs:lc_note], 1
        ret

; BL = a key: ZF = 1 when it is a mode key (wave.asm modes).  Changes AL.
lc_mode_key:
        push si
        mov si, modes
.m:     mov al, [cs:si]
        inc si
        or al, al
        jz .no
        cmp al, bl
        jne .m
        pop si
        ret
.no:    inc al                          ; ZF = 0
        pop si
        ret

; AX = word [D38C], the 100 Hz tick count (2B50:0028), read with interrupts off.
lc_ticks:
        pushf
        cli
        mov ax, [LC_TICKS]
        popf
        ret

; BL = the key the view read.  AL = 0: not handled (BL kept, the view
; dispatches it); 1: handled, read the next key; 2: handled, redraw.
lc_dispatch:
        cmp byte [cs:lc_box], 0         ; a stock error box was up during BDE3:000E
        je .boxed
        mov byte [cs:lc_box], 0
        mov al, [cs:zones_valid]
        mov [cs:lc_owned], al
        push bx
        FCALL T_C4C8_0F5F               ; the box left the LCD in text mode: the view again
        pop bx
.boxed: cmp bl, 'D'                     ; a status stays until a key that is not a pad's
        je .kept
        mov byte [cs:lc_note], 0
.kept:
        xor al, al
        xchg al, [cs:lc_ask_eq]         ; "Back to equal zones?" is open for one key
        or al, al
        jz .noask
        cmp bl, 0x0D                    ; Enter: the CHOPS map becomes N equal zones
        jne .disarm
        call zones_divide
        mov al, 2
        ret
.disarm:cmp word [cs:lc_note_ptr], lc_s_ask_eq
        jne .noask
        mov byte [cs:lc_note], 0        ; the question goes with the key that closed it,
        mov byte [cs:lc_redraw], 1      ; drawn away before the next key (lc_poll)
        cmp bl, 'D'
        jne .noask
        call lc_drain                   ; a pad: its audition, and the row redrawn
        mov al, 2
        ret
.noask: mov al, [cs:lc_phase]
        or al, al
        jz .zones
        jmp .take
.zones: cmp bl, '+'                     ; a step of the selected point: not left yet
        je .edit
        cmp bl, '-'
        je .edit
        cmp bl, 'D'                     ; a pad or a MIDI note key does not leave
        je .edit                        ; the field
        cmp bl, 'N'
        je .edit
        call lc_settle                  ; anything else leaves the field: snap it (D4)
.edit:  cmp bl, 'D'
        je lc_drain
        cmp byte [cs:onview], 2         ; the ZONE fields: the Lazy Chop soft keys
        jb .pass
        cmp bl, 'x'
        je .arm
        cmp bl, 'y'
        je .snap
        cmp bl, 'z'
        je .convert
        cmp byte [cs:onview], 3         ; CHOPS count field: offer the equal division
        jne .pass
        cmp byte [cs:zones_mode], 0
        je .pass
        cmp bl, '+'
        je .askeq
        cmp bl, '-'
        jne .pass
.askeq: mov byte [cs:lc_ask_eq], 1
        mov si, lc_s_ask_eq
        call lc_status
        mov al, 2
        ret
.pass:  xor al, al
        ret
.convert:
        cmp byte [cs:lc_self_end], 0    ; a take that ended by itself: a late <Done>
        je lc_convert                   ; (Soft Key 3) within 0.5 s is not <To program>
        call lc_ticks
        sub ax, [cs:lc_end_tick]
        cmp ax, 50
        jb .swallow
        mov byte [cs:lc_self_end], 0
        jmp lc_convert
.arm:   mov byte [cs:lc_phase], 1       ; the map stays until the first hit
        mov byte [cs:fine], 0           ; the take is shown in the full view
        mov byte [cs:lc_self_end], 0
        mov byte [cs:lc_dropped], 0     ; "Lost:nn" counts this take's hits only
        call lc_flush
        call lc_set_k
        mov al, 2
        ret
.snap:  xor byte [cs:lc_snap], 1
        mov al, 2
        ret
.take:  cmp bl, 'H'                     ; Help and the mode keys leave (lc_leave cancels)
        je .pass
        call lc_mode_key
        je .pass
        cmp bl, 'D'
        je lc_drain
        cmp bl, 'u'                     ; Soft Key 4 <Cancel>
        je .cancel
        cmp byte [cs:lc_phase], 2
        je .rec
        cmp bl, '+'                     ; Armed: the user offset
        je .offset
        cmp bl, '-'
        je .offset
.swallow:
        mov al, 1
        ret
.rec:   cmp bl, 'z'                     ; Soft Key 3 <Done>
        jne .swallow
        call lc_take_end
        mov al, 2
        ret
.cancel:call lc_take_cancel
        mov al, 2
        ret
.offset:mov al, [cs:lc_offset]
        cbw
        mov cx, [cs:key_repeat]
        cmp bl, '+'
        je .add
        neg cx
.add:   add ax, cx
        cmp ax, LC_OFFSET_MAX
        jle .low
        mov ax, LC_OFFSET_MAX
.low:   cmp ax, -LC_OFFSET_MAX
        jge .set
        mov ax, -LC_OFFSET_MAX
.set:   mov [cs:lc_offset], al
        call lc_set_k
        mov al, 2
        ret

; AL = the key at the head of KEY_QUEUE (the queue is not empty; FB00 reads
; [bx+6]-1, wrapping to the capacity, 47BF:072E).  Keeps the other registers.
lc_peek:
        push bx
        mov bx, [KEY_QUEUE+6]
        or bx, bx
        jnz .r
        mov bx, [KEY_QUEUE]
.r:     mov al, [KEY_QUEUE+8+bx-1]
        pop bx
        ret

; Before each key read.  CF = 1: redraw first; else AL = the key read here, or
; 0: the view reads the next key through BDE3:000E (only for + and -, whose
; repeats BDE3:000E coalesces, and for a stock error box).
; The view never waits inside BDE3:000E: that loop (0F6B:00A6..00D3) keeps
; reading while the global filter 3481:000E returns 0 (Pad Bank, COUNT IN, the
; kick 'P' in Edit Sound ...), so the bank shown and the error box check would
; stop.  Here every other queued key is taken without waiting (T_D6E0_0000, as
; D6E0:001B without its coalescing) and passed through the filter; the kick
; ([D398], set by the tick ISR and the MIDI-in overflow writer, img
; 0x2C3CB..0x2C3D8) is taken as D6E0:001B takes it, and filtered too.  A filter
; result of 0 loops back to the checks.
; Every phase: the bank shown follows Pad Bank (redraw when [D38F] changed).
; Zones and Armed: BDE3:000E's error box ([9331] and [A44F], 0F6B:00A6) is
; entered with the pads stock (lc_box; lc_dispatch owns them again).
; Recording: chops from the ring, STOP, and the end of the Source by the 100 Hz
; tick count (no timestamp is taken in the task), every key read here.
lc_poll:
        cmp byte [cs:lc_redraw], 0      ; a key changed row 49 without a redraw
        je .poll
        mov byte [cs:lc_redraw], 0
        stc
        ret
.poll:  mov byte [cs:lc_dirty], 0
.loop:  cmp byte [cs:lc_phase], 2
        jne .idle
        call lc_drain_take
        cmp byte [cs:lc_phase], 2
        jne .redraw                     ; 64 chops ended it
        cmp byte [LC_STOP_HELD], 0
        jne .stop
        call lc_ticks
        sub ax, [cs:lc_tick0]
        cmp ax, [cs:lc_end_ticks]
        jae .end
        cmp byte [cs:lc_dirty], 0
        jne .redraw                     ; one redraw per drain: marks stay in the cave
.idle:  mov al, [LC_BANK]
        cmp al, [cs:lc_bank_shown]
        jne .redraw
        cmp byte [cs:lc_phase], 2
        je .take
        call lc_err_box
        jne .take
        mov byte [cs:lc_owned], 0
        mov byte [cs:lc_box], 1
        jmp .bde
.take:  call lc_take_key                ; AL = a key, 0 = none
        or al, al
        jz .loop
        clc
        ret
.bde:   xor al, al                      ; CF = 0
        ret
.end:   mov byte [cs:lc_self_end], 1    ; ended by itself: a late <Done> is ignored
        call lc_ticks
        mov [cs:lc_end_tick], ax
.stop:  call lc_take_end
.redraw:stc
        ret

; ZF = 1 when BDE3:000E would open its error box now ([9331] and [A44F]).
lc_err_box:
        cmp byte [SO_ERR], 0
        je .no
        cmp byte [XP_POST_STOP], 0
        je .no
        cmp al, al                      ; ZF = 1
        ret
.no:    or sp, sp                       ; ZF = 0 (SP is never 0)
        ret

; One key without waiting: AL = the key after the global filter, 0 when there
; was none or the filter took it.  The kick is taken as D6E0:001B takes it; +
; and - are coalesced as D6E0:001B coalesces them (2D0B:00F3..010D: the copies
; of the key at the head of the queue, taken with interrupts off, counted into
; KEY_REPEAT), so the wheel steps as through BDE3:000E.
lc_take_key:
        cmp word [KEY_QUEUE+2], 0
        jne .queued
        cli
        mov al, [LC_KICK]
        mov byte [LC_KICK], 0
        sti
        or al, al
        jnz lc_filter_key
        ret
.queued:call lc_peek
        cmp al, '+'
        je .coalesce
        cmp al, '-'
        jne lc_read_key
.coalesce:
        mov [cs:lc_coal_key], al
        push cx
        mov cx, 1                       ; CX = the steps
        push cx
        FCALL T_D6E0_0000               ; the first one
        pop cx
.more:  cli
        cmp word [KEY_QUEUE+2], 0
        je .counted
        call lc_peek
        cmp al, [cs:lc_coal_key]
        jne .counted
        push cx
        FCALL T_D6E0_0000               ; a copy at the head: one more step
        pop cx
        sti
        inc cx
        jmp .more
.counted:
        sti
        mov [KEY_REPEAT], cx
        pop cx
        mov al, [cs:lc_coal_key]
        jmp lc_filter_key

; The queued key through the global filter: AL = the key, or 0 when the filter
; took it.  KEY_REPEAT = 1 (one key, as D6E0:001B counts it).
lc_read_key:
        FCALL T_D6E0_0000               ; the queued key (AL)
        mov word [KEY_REPEAT], 1
lc_filter_key:
        xor ah, ah
        push ax
        FCALL T_DE5C_000E               ; global filter: 0 when it handled the key
        add sp, 2
        ret

; The Convert page's, the Replace prompt's and a message's key wait, the way
; lc_poll reads: AL = a key (never 0).  BDE3:000E reads + and - (coalesced) and
; shows a stock error box; while the box is up the pads are stock, and
; lc_cv_boxed = 1 after it (the page is drawn again, in graphics mode).
lc_key:
.loop:  call lc_err_box
        je .box
        call lc_take_key
        or al, al
        jz .loop
        ret
.bde:   push 0
        FCALL T_BDE3_000E
        add sp, 2
.r:     ret
.box:   mov al, [cs:lc_owned]
        push ax
        mov byte [cs:lc_owned], 0
        call .bde
        mov byte [cs:lc_cv_boxed], 1
        pop dx
        mov [cs:lc_owned], dl
        ret

; Key 'D': the ring.  Zones: the latest hit plays its slot (mono); Armed: the
; first hit starts the take; Recording: chops.  AL = 1 or 2 (lc_dispatch).
lc_drain:
        mov byte [cs:lc_dirty], 0
        mov al, [cs:lc_phase]
        or al, al
        jz .zones
        cmp al, 1
        jne .take
        call lc_pop
        jc .none
        call lc_take_start
        mov byte [cs:lc_dirty], 1
.take:  call lc_drain_take
        mov al, 1
        cmp byte [cs:lc_dirty], 0
        je .r
        inc al
.r:     ret
.zones: mov bh, 0xFF
.z:     call lc_pop
        jc .zd
        mov bh, cl
        jmp .z
.zd:    cmp bh, 0xFF
        je .none
        mov cl, bh
        jmp lc_audition_slot
.none:  mov al, 1
        ret

lc_drain_take:
.n:     call lc_pop
        jnc .chop
        ret
.chop:  call lc_add_chop
        cmp byte [cs:lc_phase], 2
        je .n
        ret

; ---------------------------------------------------------------- pads play slices

; CL = slot 0..63 = bank * 16 + pad - 1: zone CL + 1 (R1, R3), selected (the
; selection follows the pad) and played once from start to end after the
; previous audition is stopped (D5).  A pad with no zone is silent.  AL = 1/2.
lc_audition_slot:
        cmp cl, [cs:zones_count]
        jae .silent
        mov al, cl
        inc al
        mov [cs:zones_current], al
        or byte [cs:sel], 2
        call zones_load
        call lc_stop_auditions
        call zones_offset
        mov ax, [cs:bx]
        mov dx, [cs:bx+2]
        mov [cs:aud_start], ax
        mov [cs:aud_start+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        mov [cs:aud_end], ax
        mov [cs:aud_end+2], dx
        sub ax, [cs:bx]                 ; under LC_MIN (a slice stock would not play
        sbb dx, [cs:bx+2]               ; after Convert): row 49 says so, until a key
        jnz .long                       ; that is not a pad's or a pad that plays
        cmp ax, LC_MIN
        jae .long
        mov si, lc_s_short
        call lc_status
        jmp .r2
.long:  call aud_range                  ; CFC6:0CE9 refuses an empty range itself
.played:cmp word [cs:lc_note_ptr], lc_s_short
        jne .r2
        mov byte [cs:lc_note], 0        ; a pad that plays takes the message away
.r2:    mov al, 2
        ret
.silent:mov al, 1
        ret

; Stop the channels the view's auditions started, if still theirs (owner 62h,
; no mute tag: not re-allocated to a pad note).  Keeps every register.
lc_stop_auditions:
        pusha
        xor bx, bx
.l:     cmp bl, [cs:lc_aud_n]
        jae .done
        mov al, [cs:lc_aud_ch+bx]
        xor ah, ah
        mov si, ax
        cmp byte [MUTE_OWNER+si], LC_OWNER_AUD
        jne .next
        cmp byte [cs:mute_voice_program+si], 0
        jne .next
        push bx
        push ax
        FCALL T_D21F_0008               ; one-channel stop
        add sp, 2
        pop bx
.next:  inc bx
        jmp .l
.done:  mov byte [cs:lc_aud_n], 0
        popa
        ret

; From mute_voice_alloc_wrapper after every allocation while the view owns the
; pads or lists channels (lc_owned or lc_aud_n), BP = its frame, BX = the
; channel.  The chain CFC6:0B2D <- 039E <- 0CE9 <- aud_range is the one
; aud_range started (the frames audition_callsite reads): its channel is
; listed for the mono stop; any other allocation of a listed channel (a pad
; or sequence note reusing it) takes it off the list, so the stop never hits a
; foreign voice.  Keeps every register.
lc_alloc_seen:
        push ax
        push si
        cmp byte [cs:lc_owned], 0
        je .other
        mov si, [bp]                    ; CFC6:0B2D frame
        mov si, [ss:si]                 ; CFC6:039E frame
        cmp word [ss:si+2], PLAYER_CE9_RET
        jne .other
        cmp word [ss:si+4], strict word PLAYER_SEG
        RELOC_PREV
        jne .other
        mov si, [ss:si]                 ; CFC6:0CE9 frame
        cmp word [ss:si+2], aud_range.return_from_stock
        jne .other
        mov ax, cs
        cmp [ss:si+4], ax
        jne .other
        mov al, [cs:lc_aud_n]
        cmp al, 4
        jae .r
        xor ah, ah
        mov si, ax
        mov [cs:lc_aud_ch+si], bl
        inc byte [cs:lc_aud_n]
        jmp .r
.other: xor si, si                      ; drop BL from the list
.scan:  mov ax, si
        cmp al, [cs:lc_aud_n]
        jae .r
        cmp [cs:lc_aud_ch+si], bl
        je .drop
        inc si
        jmp .scan
.drop:  dec byte [cs:lc_aud_n]          ; the last entry takes its place
        push bx
        mov bl, [cs:lc_aud_n]
        xor bh, bh
        mov al, [cs:lc_aud_ch+bx]
        mov [cs:lc_aud_ch+si], al
        pop bx
.r:     pop si
        pop ax
        ret

; ---------------------------------------------------------------- the take

; First hit: chop 1 = frame 0 (D2), the whole Source plays at Tune 0 (D10),
; t0 = the time right after CFC6:0CE9 returns.
lc_take_start:
        call lc_stop_auditions
        mov byte [cs:lc_phase], 2
        mov byte [cs:lc_nchops], 1
        mov byte [cs:lc_dropped], 0
        xor ax, ax
        mov [cs:lc_chops], ax
        mov [cs:lc_chops+2], ax
        mov [cs:aud_start], ax
        mov [cs:aud_start+2], ax
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        mov [cs:aud_end], ax
        mov [cs:aud_end+2], dx
        mov byte [cs:lc_tune0], 1
        call aud_range
        mov byte [cs:lc_tune0], 0
        call lc_time
lc_t0_stamped:
        mov [cs:lc_t0], ax
        mov [cs:lc_t0+2], dx
        call lc_ticks                   ; the end, in 100 Hz ticks from here:
        mov [cs:lc_tick0], ax           ; ceil(len / 441) + ceil(offset / 10 ms) + 1
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        add ax, 440
        adc dx, 0
        mov cx, 441
        div cx
        mov cx, ax
        mov al, [cs:lc_offset]
        cbw
        add ax, 29
        mov dl, 10
        div dl                          ; (offset + 29) div 10 = ceil(offset / 10) + 2
        xor ah, ah
        add ax, cx
        dec ax                          ; - 2 + 1 tick of margin
        jg .ticks
        mov ax, 1
.ticks: mov [cs:lc_end_ticks], ax
        ret

; DX:AX = a hit's time: a chop at its position, in time order (D3), unless
; under 441 frames after the previous chop or within 441 of the end.
lc_add_chop:
        call lc_pos
        mov bx, ax
        mov cx, dx
        add bx, LC_MIN
        adc cx, 0
        cmp cx, [cs:len+2]
        ja .r
        jb .gap
        cmp bx, [cs:len]
        ja .r
.gap:   xor bx, bx
        mov bl, [cs:lc_nchops]
        dec bx
        shl bx, 2
        mov si, ax
        mov di, dx
        sub si, [cs:lc_chops+bx]
        sbb di, [cs:lc_chops+bx+2]
        jb .r
        or di, di
        jnz .add
        cmp si, LC_MIN
        jb .r
.add:   mov [cs:lc_chops+bx+4], ax
        mov [cs:lc_chops+bx+6], dx
        inc byte [cs:lc_nchops]
        mov byte [cs:lc_dirty], 1
        cmp byte [cs:lc_nchops], LC_MAX
        jb .r
        mov si, lc_s_max                ; "Too many slices (64)"
        call lc_status
        mov byte [cs:lc_self_end], 1    ; ended by itself: a late <Done> is ignored
        call lc_ticks
        mov [cs:lc_end_tick], ax
        call lc_take_end
.r:     ret

lc_take_cancel:
        mov byte [cs:lc_phase], 0
        call lc_stop_auditions
        jmp lc_flush

; End (Source end, STOP, <Done>, 64 chops): the take becomes a CHOPS map,
; slice k = {chop k, chop k+1}, the last ending at the Source end; with snap
; on (D4) each chop after the first moves to the nearest zero crossing within
; 2 ms that keeps both its slices at least 441 frames.  Refine: slice 1.
lc_take_end:
        call lc_stop_auditions
        cmp byte [cs:lc_snap], 0
        je .pairs
        mov si, 1
.snap:  mov ax, si
        cmp al, [cs:lc_nchops]
        jae .pairs
        mov bx, si
        shl bx, 2
        mov ax, [cs:lc_chops+bx-4]      ; lo = previous chop + 441
        mov dx, [cs:lc_chops+bx-2]
        add ax, LC_MIN
        adc dx, 0
        mov [cs:lc_lo], ax
        mov [cs:lc_lo+2], dx
        mov ax, [cs:len]                ; hi = next chop (or the end) - 441
        mov dx, [cs:len+2]
        mov cx, si
        inc cx
        cmp cl, [cs:lc_nchops]
        jae .hi
        mov ax, [cs:lc_chops+bx+4]
        mov dx, [cs:lc_chops+bx+6]
.hi:    sub ax, LC_MIN
        sbb dx, 0
        mov [cs:lc_hi], ax
        mov [cs:lc_hi+2], dx
        mov ax, [cs:lc_chops+bx]
        mov dx, [cs:lc_chops+bx+2]
        push bx
        call lc_snap_point
        pop bx
        mov [cs:lc_chops+bx], ax
        mov [cs:lc_chops+bx+2], dx
        inc si
        jmp .snap
.pairs: xor cx, cx
        mov cl, [cs:lc_nchops]
        mov si, lc_chops
        mov di, zones_pairs
.p:     mov ax, [cs:si]
        mov dx, [cs:si+2]
        mov [cs:di], ax
        mov [cs:di+2], dx
        mov ax, [cs:si+4]
        mov dx, [cs:si+6]
        cmp cx, 1
        jne .end
        mov ax, [cs:len]
        mov dx, [cs:len+2]
.end:   mov [cs:di+4], ax
        mov [cs:di+6], dx
        add si, 4
        add di, 8
        loop .p
        mov al, [cs:lc_nchops]
        mov [cs:zones_count], al
        mov byte [cs:zones_mode], 1
        mov byte [cs:zones_current], 1
        mov byte [cs:sel], 2
        mov byte [cs:lc_phase], 0
        call zones_load
        jmp lc_flush

; ---------------------------------------------------------------- CHOPS edits (move)

; From zones_limits, CHOPS zone pair: start in [0, end-441], end in [start+441, len].
lc_chops_limits:
        test byte [cs:sel], 1
        jnz .end
        sub word [cs:hi], LC_MIN
        sbb word [cs:hi+2], 0
        ret
.end:   add word [cs:lo], LC_MIN
        adc word [cs:lo+2], 0
        ret

; From move, DX:AX = the edited value before move's clamp: CF = 1 refuses a
; CHOPS slice edit outside [lo, hi] (the previous value is kept).
lc_refuse:
        cmp byte [cs:zones_mode], 0
        je .ok
        test byte [cs:sel], 2
        jz .ok
        cmp dx, [cs:lo+2]
        jl .no
        jg .high
        cmp ax, [cs:lo]
        jb .no
.high:  cmp dx, [cs:hi+2]
        jg .no
        jl .ok
        cmp ax, [cs:hi]
        ja .no
.ok:    clc
        ret
.no:    stc
        ret

; After move stored a CHOPS slice's start or end (D4): a committed value (numeric
; entry) snaps at once; a wheel or +/- step does not (the next step would come
; back to the same crossing), the point is marked (slice, start or end) and
; lc_settle snaps it when the field is left (any key but +/-, a pad or a MIDI
; note key), before Convert and when the view closes.
lc_after_move:
        cmp byte [cs:zones_mode], 0
        je .r
        test byte [cs:sel], 2
        jz .r
        mov al, [cs:zones_current]
        dec al
        mov ah, [cs:sel]
        and ah, 1
        cmp byte [cs:lc_edit_dirty], 0  ; another point still stepped and not snapped
        je .mark                        ; (a pad selected another slice): snap it first
        cmp al, [cs:lc_edit_slice]
        jne .other
        cmp ah, [cs:lc_edit_point]
        je .mark
.other: push ax
        call lc_settle
        pop ax
.mark:  mov [cs:lc_edit_slice], al
        mov [cs:lc_edit_point], ah
        mov byte [cs:lc_edit_dirty], 1
        cmp byte [cs:lc_commit], 0
        jne lc_settle
.r:     ret

; Snap the point lc_after_move marked, if snap is on, and only that point: a
; start within [0, end - LC_MIN], an end within [start + LC_MIN, len].  Frame 0
; and the Source end are never moved (D2).  Keeps every register.
lc_settle:
        cmp byte [cs:lc_edit_dirty], 0
        je .r
        pusha
        mov byte [cs:lc_edit_dirty], 0
        cmp byte [cs:lc_snap], 0
        je .done
        cmp byte [cs:zones_mode], 0
        je .done
        mov al, [cs:lc_edit_slice]
        cmp al, [cs:zones_count]
        jae .done
        xor bx, bx
        mov bl, al
        shl bx, 3
        add bx, zones_pairs
        cmp byte [cs:lc_edit_point], 0
        jne .end
        mov ax, [cs:bx]                 ; the start: not frame 0
        or ax, [cs:bx+2]
        jz .done
        xor ax, ax
        mov [cs:lc_lo], ax
        mov [cs:lc_lo+2], ax
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        sub ax, LC_MIN
        sbb dx, 0
        mov [cs:lc_hi], ax
        mov [cs:lc_hi+2], dx
        mov ax, [cs:bx]
        mov dx, [cs:bx+2]
        push bx
        call lc_snap_point
        pop bx
        mov [cs:bx], ax
        mov [cs:bx+2], dx
        jmp .load
.end:   mov ax, [cs:bx+4]               ; the end: not the Source end
        mov dx, [cs:bx+6]
        cmp ax, [cs:len]
        jne .moved
        cmp dx, [cs:len+2]
        je .done
.moved: mov ax, [cs:bx]
        mov dx, [cs:bx+2]
        add ax, LC_MIN
        adc dx, 0
        mov [cs:lc_lo], ax
        mov [cs:lc_lo+2], dx
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        mov [cs:lc_hi], ax
        mov [cs:lc_hi+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        push bx
        call lc_snap_point
        pop bx
        mov [cs:bx+4], ax
        mov [cs:bx+6], dx
.load:  call zones_load
.done:  popa
.r:     ret

; ---------------------------------------------------------------- snap

; DX:AX = frame s -> DX:AX = the nearest zero crossing p with |p - s| <= 88
; and lc_lo <= p <= lc_hi, else s.  Reads plane L around s into SND_SEG:0000
; (BUSY held, as the view's fill).  Keeps SI, DI.
lc_snap_point:
        push si
        push di
        mov [cs:lc_s], ax
        mov [cs:lc_s+2], dx
        sub ax, LC_SNAP_W + 1           ; from = max(0, s - 89)
        sbb dx, 0
        jnc .from
        xor ax, ax
        xor dx, dx
.from:  mov [cs:lc_from], ax
        mov [cs:lc_from+2], dx
        mov bx, [cs:lc_s]               ; to = min(len, s + 89)
        mov cx, [cs:lc_s+2]
        add bx, LC_SNAP_W + 1
        adc cx, 0
        cmp cx, [cs:len+2]
        jb .to
        ja .tolen
        cmp bx, [cs:len]
        jbe .to
.tolen: mov bx, [cs:len]
.to:    sub bx, ax                      ; count <= 178
        cmp bx, 2
        jb .keep
        mov cx, bx
        mov ax, [cs:wbase]
        mov dx, [cs:wbase+2]
        add ax, [cs:lc_from]
        adc dx, [cs:lc_from+2]
        push cx
        inc byte [BUSY]
        push 1                          ; read
        push 0
        push cx
        push dx
        push ax
        push strict word SND_SEG
        RELOC_PREV
        push 0
        FCALL T_CF92_000C
        add sp, 14
        dec byte [BUSY]
        pop cx
        mov bx, [cs:lc_s]               ; s, lo and hi relative to from
        sub bx, [cs:lc_from]
        mov ax, [cs:lc_lo]
        mov dx, [cs:lc_lo+2]
        sub ax, [cs:lc_from]
        sbb dx, [cs:lc_from+2]
        jb .lo1
        or dx, dx
        jnz .keep
        cmp ax, 1
        jae .lo
.lo1:   mov ax, 1
.lo:    mov si, ax
        mov ax, [cs:lc_hi]
        mov dx, [cs:lc_hi+2]
        sub ax, [cs:lc_from]
        sbb dx, [cs:lc_from+2]
        jb .keep
        mov di, cx
        dec di
        or dx, dx
        jnz .search
        cmp ax, di
        jae .search
        mov di, ax
.search:call lc_snap_search
        jc .keep
        xor dx, dx
        add ax, [cs:lc_from]
        adc dx, [cs:lc_from+2]
        jmp .r
.keep:  mov ax, [cs:lc_s]
        mov dx, [cs:lc_s+2]
.r:     pop di
        pop si
        ret

; Words at SND_SEG:0000.  BX = s, SI = lowest allowed p (>= 1), DI = highest.
; A zero crossing at p: word p is 0, or words p-1 and p differ in sign.  The
; nearest from s, p = s + d before s - d.  AX = p, CF = 0; CF = 1: none.
; Keeps BX, CX, DX, SI, DI.
lc_snap_search:
        push es
        push cx
        push dx
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        xor cx, cx
.d:     mov ax, bx
        add ax, cx
        call .try
        jnc .found
        jcxz .next
        mov ax, bx
        sub ax, cx
        jc .next
        call .try
        jnc .found
.next:  inc cx
        cmp cx, LC_SNAP_W
        jbe .d
        stc
        jmp .r
.found: clc
.r:     pop dx
        pop cx
        pop es
        ret
.try:   cmp ax, si
        jb .no
        cmp ax, di
        ja .no
        push bx
        mov bx, ax
        shl bx, 1
        mov dx, [es:bx]
        or dx, dx
        jz .yes
        xor dx, [es:bx-2]
        js .yes
        pop bx
.no:    stc
        ret
.yes:   pop bx
        clc
        ret

; ---------------------------------------------------------------- drawing (wave.asm draw)

; DX:AX = a frame -> AX = its column, CF = 1 when it is off the view.
lc_column:
        cmp byte [cs:fine], 0
        jne .fine
        mov bx, [cs:len]
        mov cx, [cs:len+2]
.shift: or cx, cx                       ; len < 2^24: at most 8 shifts
        jz .div
        shr cx, 1
        rcr bx, 1
        shr dx, 1
        rcr ax, 1
        jmp .shift
.div:   or bx, bx
        jz .off
        or dx, dx
        jnz .last
        cmp ax, bx
        ja .last
        mov cx, COLS
        mul cx
        div bx
        cmp ax, COLS
        jb .on
.last:  mov ax, COLS - 1
.on:    clc
        ret
.fine:  sub ax, [cs:center]
        sbb dx, [cs:center+2]
        mov bx, ax
        sar bx, 15
        cmp bx, dx
        jne .off
        mov cx, [cs:zoom]
        cwd
        idiv cx
        or dx, dx
        jns .floor
        dec ax                          ; floor for a negative remainder
.floor: add ax, COLS / 2
        cmp ax, COLS
        jb .on
.off:   stc
        ret

; Ticks over the top 4 wave rows: each chop after the first while recording,
; each slice start after the first in a CHOPS map.
lc_markers:
        push bp
        cmp byte [cs:lc_phase], 2
        je .take
        cmp byte [cs:lc_phase], 0
        jne .r
        cmp byte [cs:zones_mode], 0
        je .r
        xor cx, cx
        mov cl, [cs:zones_count]
        mov si, zones_pairs + 8
        mov bp, 8
        jmp .go
.take:  xor cx, cx
        mov cl, [cs:lc_nchops]
        mov si, lc_chops + 4
        mov bp, 4
.go:    dec cx
        jle .r
.m:     push cx
        push si
        mov ax, [cs:si]
        mov dx, [cs:si+2]
        call lc_column
        jc .skip
        mov bx, ax
        mov cx, 1
        mov ax, TOP
        mov dx, 4
        call invert
.skip:  pop si
        pop cx
        add si, bp
        loop .m
.r:     pop bp
        ret

; Row 49 from column 26: "Bank A" (Zones; the bank shown is remembered, lc_poll
; redraws when Pad Bank changes it) and, at column 33 while the ZONE fields are
; not focused, the hint "Chop:>>" (Right, Right: the Lazy Chop soft keys); a pad
; on a slice under two player ticks shows "Slice too short"; the take shows
; "Offset:+00ms"; a status (lc_status) takes the whole row until the next key.
lc_row49:
        mov al, [LC_BANK]
        mov [cs:lc_bank_shown], al
        cmp byte [cs:lc_note], 0
        jne .note
        cmp byte [cs:lc_phase], 0
        jne .offset
        shr al, 4
        and al, 3
        add al, 'A'
        mov [cs:lc_s_bank+5], al
        mov si, lc_s_bank
        call .text
        cmp byte [cs:onview], 2
        jae .r
        cmp byte [cs:fine], 0
        jne .r
        mov ax, 49
        mov bx, 33
        mov si, lc_s_hint
        jmp text
.r:     ret
.offset:mov al, [cs:lc_offset]
        mov byte [cs:lc_s_off+7], '+'
        or al, al
        jns .plus
        neg al
        mov byte [cs:lc_s_off+7], '-'
.plus:  xor ah, ah
        mov di, lc_s_off + 8
        mov cx, 2
        call digits
        mov si, lc_s_off
.text:  mov ax, 49
        mov bx, 26
        jmp text
.note:  mov si, [cs:lc_note_ptr]
.status:push si
        push es
        push ds
        pop es
        mov di, FB + ROW * 49
        mov cx, ROW * 7 / 2
        xor ax, ax
        rep stosw
        pop es
        pop si
        mov ax, 49
        xor bx, bx
        jmp text

; Row 57: Armed, Recording and the zone page's soft keys.  CF = 1: drawn.
lc_softkeys:
        mov al, [cs:lc_phase]
        cmp al, 1
        je .armed
        cmp al, 2
        je .rec
        cmp byte [cs:onview], 2
        jae .zone
        clc
        ret
.armed: mov si, lc_s_hit
        xor bx, bx
        call .put
        jmp .cancel
.rec:   xor ax, ax
        mov al, [cs:lc_nchops]
        mov di, lc_s_chops + 7
        mov cx, 2
        call digits
        mov si, lc_s_chops
        xor bx, bx
        call .put
        mov al, [cs:lc_dropped]         ; hits lost on a full ring, if any
        or al, al
        jz .nolost
        xor ah, ah
        mov di, lc_s_lost + 5
        mov cx, 2
        call digits
        mov si, lc_s_lost
        mov bx, 10
        call .put
.nolost:mov si, lc_s_done
        mov bx, 21
        call .put
.cancel:mov si, lc_s_cancel
        mov bx, 32
        call .put
        stc
        ret
.zone:  mov si, lc_s_lazy
        xor bx, bx
        call .put
        mov si, lc_s_snap_on
        cmp byte [cs:lc_snap], 0
        jne .snap
        mov si, lc_s_snap_off
.snap:  mov bx, 12
        call .put
        mov si, lc_s_toprog
        mov bx, 21
        call .put
        mov si, s_exit
        mov bx, 34
        call .put
        stc
        ret
.put:   mov ax, 57
        jmp text

; ---------------------------------------------------------------- slice names (D6)

; CX = the Source name's length with trailing spaces (and anything from a NUL)
; dropped, 0..16.  Changes AL, BX.
lc_src_len:
        xor cx, cx
        xor bx, bx
.c:     mov al, [cs:zones_identity+bx]
        or al, al
        jz .r
        inc bx
        cmp al, ' '
        je .sp
        mov cx, bx
.sp:    cmp bx, 16
        jb .c
.r:     ret

; chop_create_all's name for zone chop_zone.  chop_naming = 0 (CHOP ZONE):
; ZONEnnn (chop_make_name).  1 (Convert, D6): the Source's name + the slice
; number k, unique among the Sounds in memory and the .SND files of the
; selected disk (lc_disk_scan, numbers under LC_DISK_N): <name, at most 13
; chars><k, 2 digits>; if that name exists, k + 100, k + 200, ... with the name
; cut to keep 16 characters (12 + 3 digits, 11 + 4, 10 + 5).  Never ZONEnnn.
; Preserves BX, CX, SI, DI.
chop_name_slice:
        push bx
        push cx
        push si
        push di
        cmp byte [cs:chop_naming], 0
        jne .slice
        call chop_make_name
        jmp .done
.slice: call lc_src_len
        mov [cs:lc_name_len], cx
        xor ax, ax
        mov al, [cs:chop_zone]
        inc ax
        mov [cs:lc_name_n], ax
.try:   mov ax, [cs:lc_name_n]
        mov cx, 2                       ; digits of n
        cmp ax, 100
        jb .width
        inc cx
        cmp ax, 1000
        jb .width
        inc cx
        cmp ax, 10000
        jb .width
        inc cx
.width: mov dx, 15                      ; the name: min(length, 15 - digits) characters
        sub dx, cx
        cmp dx, [cs:lc_name_len]
        jbe .cut
        mov dx, [cs:lc_name_len]
.cut:   xor bx, bx
.copy:  cmp bx, dx
        jae .num
        mov al, [cs:zones_identity+bx]
        mov [cs:chop_name+bx], al
        inc bx
        jmp .copy
.num:   lea di, [chop_name+bx]
        mov ax, [cs:lc_name_n]
        call digits                     ; CX digits at DI, DI past them (BX, DX change)
        mov bx, di
        sub bx, chop_name
.pad:   cmp bx, 16
        jae .named
        mov byte [cs:chop_name+bx], ' '
        inc bx
        jmp .pad
.named: mov byte [cs:chop_name+16], 0
        mov bx, [cs:lc_name_n]          ; a .SND file of the selected disk has it
        cmp bx, LC_DISK_N               ; (lc_disk_scan)
        jae .memory
        mov cl, bl
        and cl, 7
        shr bx, 3
        mov al, 1
        shl al, cl
        test [cs:lc_taken+bx], al
        jnz .taken
.memory:push cs
        push chop_name
        FCALL T_D0C0_0D17
        add sp, 4
        or ax, ax
        js .done                        ; -4: no Sound has the name
.taken: add word [cs:lc_name_n], 100
        cmp word [cs:lc_name_n], 65000
        jb .try
.done:  pop di
        pop si
        pop cx
        pop bx
        ret

; The selected disk's .SND names of the Convert form: lc_taken bit n set for
; each file named <the Source's first min(len, 15 - d) characters><n, d = 2 or 3
; digits>, n < LC_DISK_N (stock find first / next, 200D:017B / 01E7, INT 41
; fn 9, on the floppy or the selected SCSI partition, as Erase all uses them).
; lc_disk_ok = 0 when the directory could not be read (find first < 0 and not
; LC_FIND_NONE: no disk, a read error); the names are then unique in memory
; only and the success message says so.
lc_disk_scan:
        push es
        push cs
        pop es
        mov di, lc_taken
        mov cx, LC_DISK_N / 8
        xor al, al
        rep stosb
        pop es
        mov byte [cs:lc_disk_ok], 0
        call lc_src_len
        mov [cs:lc_name_len], cx
        push cs
        push lc_find
        push cs
        push era_s_all
        FCALL T_CEE6_0175               ; find first
        add sp, 8
        mov [cs:lc_disk_rc], ax
        cmp ax, LC_FIND_NONE            ; a readable directory without a file
        je .read
        or ax, ax
        jnz .r
.file:  call lc_disk_entry
        push cs
        push lc_find
        push cs
        push era_s_all
        FCALL T_CEE6_01E1               ; find next
        add sp, 8
        mov [cs:lc_disk_rc], ax
        or ax, ax
        jz .file
.read:  mov byte [cs:lc_disk_ok], 1
.r:     ret

; lc_find's raw name (+7: 8 or 16 characters, 3 of extension, NUL) -> its bit.
lc_disk_entry:
        mov si, lc_find + 7
        mov bx, 8                       ; short/long as the stock formatter 077D:194D
        cmp byte [cs:si+11], 0
        je .ext
        mov bx, 16
.ext:   cmp word [cs:si+bx], 'SN'
        jne .r
        cmp byte [cs:si+bx+2], 'D'
        jne .r
.trim:  or bx, bx                       ; BX = the name's length without spaces
        jz .r
        cmp byte [cs:si+bx-1], ' '
        jne .tail
        dec bx
        jmp .trim
.tail:  mov dx, bx                      ; DX = that length
        mov cx, 2                       ; d = 2 and 3 digits: the prefix chop_name_slice
.d:     mov ax, [cs:lc_name_len]        ; writes for them is p = min(length, 15 - d)
        mov di, 15
        sub di, cx
        cmp ax, di
        jbe .p
        mov ax, di
.p:     mov di, ax                      ; DI = p
        add ax, cx
        cmp ax, dx                      ; the name is p + d characters
        jne .next
        xor bx, bx
.cmp:   cmp bx, di                      ; its first p are the Source's
        jae .num
        mov al, [cs:si+bx]
        cmp al, [cs:zones_identity+bx]
        jne .next
        inc bx
        jmp .cmp
.num:   push si                         ; its last d are digits: n
        push cx
        add si, di
        xor ax, ax
.n:     mov bl, [cs:si]
        sub bl, '0'
        cmp bl, 9
        ja .bad
        push dx
        mov dx, 10
        mul dx
        pop dx
        xor bh, bh
        add ax, bx
        inc si
        loop .n
        pop cx
        pop si
        cmp cx, 3                       ; 3 digits: n >= 100 (as digits writes it)
        jne .mark
        cmp ax, 100
        jb .next
.mark:  push cx
        mov bx, ax
        mov cl, bl
        and cl, 7
        shr bx, 3
        mov al, 1
        shl al, cl
        or [cs:lc_taken+bx], al
        pop cx
.next:  inc cx
        cmp cx, 3
        jbe .d
.r:     ret
.bad:   pop cx
        pop si
        jmp .next

; ---------------------------------------------------------------- Convert (spec section 3.4)

; <To program>: the Slices to Program page.  AL = 2 back to the view, or AL = 0
; with BL = a mode key (the view leaves with it).  <Do it> is ENTER, a key that
; never opens the page (Soft Key 3 <To program> opens it; Soft Key 1 is
; <Lazy chop> / <Ply/Stp>): queued soft keys and ENTER are dropped when the
; page is drawn, and ENTER counts only 0.25 s after the page was drawn and after
; the previous key (a mashed burst never reaches it).  Replace is a further,
; different key (Soft Key 2), with the same guard.
lc_convert:
        call lc_settle                  ; a stepped point snaps before anything is made
        call lc_cv_default
        mov byte [cs:lc_cv_choke], 1    ; D7: ON
        mov byte [cs:lc_cv_focus], 0
        mov byte [cs:lc_cv_typing], 0
        mov word [cs:lc_cv_status], 0
        call lc_cv_draw
        call fast_blit
        call lc_cv_arm                  ; drop queued keys, start the 0.25 s guard
        jmp .key
.draw:  call lc_cv_draw
        call fast_blit
.key:   call lc_cv_key                  ; BL = the key, lc_cv_stale
        jc .draw                        ; a stock error box was up: the page again
        mov ax, [KEY_REPEAT]
        or ax, ax
        jnz .repeat
        inc ax
.repeat:mov [cs:key_repeat], ax
        cmp bl, 'D'                     ; pads are owned but play nothing here
        jne .notpad
        call lc_flush
        jmp .key
.notpad:mov word [cs:lc_cv_status], 0
        cmp bl, '0'
        jb .notdigit
        cmp bl, '9'
        jbe .digit
.notdigit:
        mov byte [cs:lc_cv_typing], 0
        cmp bl, 0x0D                    ; ENTER <Do it>
        je .doit
        cmp bl, 'u'                     ; Soft Key 4 <Cancel>
        je .back
        cmp bl, 'H'
        je .back
        cmp bl, '<'
        je .focus0
        cmp bl, '^'
        je .focus0
        cmp bl, '>'
        je .focus1
        cmp bl, '!'
        je .focus1
        cmp bl, '+'
        je .adjust
        cmp bl, '-'
        je .adjust
        call lc_mode_key
        je .leave
        jmp .key
.focus0:mov byte [cs:lc_cv_focus], 0
        jmp .draw
.focus1:mov byte [cs:lc_cv_focus], 1
        jmp .draw
.adjust:cmp byte [cs:lc_cv_focus], 0
        jne .choke
        xor ax, ax
        mov al, [cs:lc_cv_prog]
        mov cx, [cs:key_repeat]
        mov dx, 23
        call mute_ui_step
        mov [cs:lc_cv_prog], al
        jmp .draw
.choke: xor al, al
        cmp bl, '+'
        jne .set
        inc al
.set:   mov [cs:lc_cv_choke], al
        jmp .draw
.digit: cmp byte [cs:lc_cv_focus], 0
        jne .key
        sub bl, '0'
        xor ax, ax
        cmp byte [cs:lc_cv_typing], 0
        je .first
        mov al, [cs:lc_cv_number]
        mov cl, 10
        mul cl
.first: xor bh, bh
        add ax, bx
        mov [cs:lc_cv_number], al
        xor byte [cs:lc_cv_typing], 1
        or ax, ax
        jz .draw
        dec ax
        cmp ax, 23
        jbe .number
        mov ax, 23
.number:mov [cs:lc_cv_prog], al
        jmp .draw
.doit:  cmp byte [cs:lc_cv_stale], 0
        jne .key                        ; within 0.25 s of the page or of a key
        ; The stock Do handlers' safe lock (chop_do_dispatch): nothing is made
        ; while the transport runs and "Lock Edit Sound <Do>" is on (0 = ON).
        cmp byte [CHOP_SEQ_STATE], 0
        je .unlocked
        cmp byte [CHOP_SAFE_LOCK], 0
        jne .unlocked
        mov word [cs:lc_cv_status], lc_s_locked
        jmp .draw
.unlocked:
        call lc_cv_check                ; every slice playable after Convert, else
        jnc .lengths                    ; "Slice nn too short", nothing made (a
        call lc_message                 ; message: the pads are stock until its key)
        jmp lc_flush                    ; AL, BL kept
.lengths:
        mov al, [cs:lc_cv_prog]
        call lc_cv_empty
        jz .run
.prompt:call lc_cv_draw                 ; not empty: "Replace program nn?"
        mov ax, 40
        xor bx, bx
        mov si, lc_s_replace
        call lc_cv_numbered             ; the program number into it
        call text
        mov di, FB + ROW * 57
        call lc_clear7
        mov ax, 57
        mov bx, 10
        mov si, lc_s_doreplace          ; <Replace> on Soft Key 2
        call text
        mov ax, 57
        mov bx, 32
        mov si, lc_s_cancel
        call text
        call fast_blit
        call lc_cv_arm
.ask:   call lc_cv_key
        jc .prompt
        cmp bl, 'D'                     ; pad hits leave the prompt open
        jne .notask
        call lc_flush
        jmp .ask
.notask:cmp bl, 'y'
        jne .kept
        cmp byte [cs:lc_cv_stale], 0
        je .run
.kept:  call lc_mode_key
        je .leave
        mov si, lc_s_kept               ; any other key: said so, nothing replaced
        call lc_cv_numbered
        mov [cs:lc_cv_status], si
        jmp .draw
.run:   call lc_cv_run                  ; AL = 2, or AL = 0 with BL = a mode key
        ret
.back:  mov al, 2
        ret
.leave: xor al, al
        ret

; The page's key: BL = it; lc_cv_stale = 1 when it came within 0.25 s of the
; page (or prompt) being drawn or of the previous key; the guard restarts at
; every key but a pad's 'D', a MIDI note's 'N' and the kick 'P' (keys nobody
; mashes: a MIDI stream would hold ENTER off for good).  CF = 1: a stock error
; box was shown (draw the page again, in graphics mode; the key is dropped).
lc_cv_key:
        mov byte [cs:lc_cv_boxed], 0
        call lc_key
        mov bl, al
        cmp bl, 'D'
        je .boxed
        cmp bl, 'N'
        je .boxed
        cmp bl, 'P'
        je .boxed
        call lc_ticks
        mov cx, ax
        sub ax, [cs:lc_cv_tick]
        mov [cs:lc_cv_tick], cx
        cmp ax, 25
        sbb al, al
        and al, 1
        mov [cs:lc_cv_stale], al
.boxed: cmp byte [cs:lc_cv_boxed], 0
        je .r
        push bx
        FCALL T_C4C8_0F5F               ; the box left the LCD in text mode
        pop bx
        stc
        ret
.r:     clc
        ret

; Drop the queued soft keys and ENTER at the head of the queue (a key pressed
; before the page was drawn is not for it) and note the 100 Hz tick of the page.
lc_cv_arm:
.drop:  cmp word [KEY_QUEUE+2], 0
        je .armed
        call lc_peek
        cmp al, 0x0D
        je .take
        cmp al, 'u'
        je .take
        sub al, 'x'                     ; x, y, z
        cmp al, 2
        ja .armed
.take:  FCALL T_D6E0_0000
        jmp .drop
.armed: call lc_ticks
        mov [cs:lc_cv_tick], ax
        ret

; Every slice at least LC_MIN frames (what stock 3.16 keys on, see LC_MIN):
; CF = 0; else CF = 1, SI = "Slice nn too short" for the first one under it.
lc_cv_check:
        xor cx, cx
        mov si, zones_pairs
.s:     cmp cl, [cs:zones_count]
        jae .ok
        mov ax, [cs:si+4]
        mov dx, [cs:si+6]
        sub ax, [cs:si]
        sbb dx, [cs:si+2]
        jnz .next                       ; >= 65536 frames
        cmp ax, LC_MIN
        jb .short
.next:  add si, 8
        inc cx
        jmp .s
.ok:    clc
        ret
.short: mov ax, cx
        inc ax
        mov di, lc_s_slice_short + 6
        mov cx, 2
        call digits
        mov si, lc_s_slice_short
        stc
        ret

; SI = a string with "00" at +16 (lc_s_replace / lc_s_kept): the destination's
; number written there.  Keeps SI.  Changes AX, BX, CX, DX, DI.
lc_cv_numbered:
        push ax
        push bx
        lea di, [si+16]
        xor ax, ax
        mov al, [cs:lc_cv_prog]
        inc ax
        mov cx, 2
        call digits
        pop bx
        pop ax
        ret

; The new program's name (record +0, 16 characters and a NUL): the Source's
; name, or, when another program already has it, <the name, at most 14
; characters><2 digits m>, m = 02, 03, ...  Changes AX, BX, CX, DX, SI, DI, ES.
lc_cv_name:
        call lc_src_len
        mov [cs:lc_name_len], cx
        mov word [cs:lc_name_n], 1
.try:   mov dx, [cs:lc_name_len]
        cmp word [cs:lc_name_n], 1
        je .base
        cmp dx, 14
        jbe .base
        mov dx, 14
.base:  xor bx, bx
.copy:  cmp bx, dx
        jae .num
        mov al, [cs:zones_identity+bx]
        mov [cs:lc_line+bx], al
        inc bx
        jmp .copy
.num:   cmp word [cs:lc_name_n], 1
        je .pad
        lea di, [lc_line+bx]
        mov ax, [cs:lc_name_n]
        mov cx, 2
        call digits
        mov bx, di
        sub bx, lc_line
.pad:   cmp bx, 16
        jae .built
        mov byte [cs:lc_line+bx], ' '
        inc bx
        jmp .pad
.built: mov byte [cs:lc_line+16], 0
        xor ax, ax                      ; every other program's name
.prog:  cmp al, [cs:lc_cv_prog]
        je .next
        push ax
        call lc_cv_record
        jz .free
        xor si, si
        xor dl, dl                      ; DL = 1 past the record name's NUL
.cmp:   mov al, [es:bx+si]
        or dl, dl
        jnz .blank
        or al, al
        jnz .have
        inc dl
.blank: mov al, ' '
.have:  cmp al, [cs:lc_line+si]
        jne .free
        inc si
        cmp si, 16
        jb .cmp
        pop ax                          ; the same name: the next number
        inc word [cs:lc_name_n]
        cmp word [cs:lc_name_n], 2
        jae .again
        mov word [cs:lc_name_n], 2
.again: cmp word [cs:lc_name_n], 99
        jbe .try
        jmp .write
.free:  pop ax
.next:  inc al
        cmp al, MUTE_PROGRAM_COUNT
        jb .prog
.write: mov al, [cs:lc_cv_prog]
        call lc_cv_record
        jz .r
        xor si, si
.w:     mov al, [cs:lc_line+si]
        mov [es:bx+si], al
        inc si
        cmp si, 17
        jb .w
.r:     ret

; DI = a framebuffer row: zero its 7 rows.  Changes AX, CX, DI.
lc_clear7:
        push es
        push ds
        pop es
        mov cx, ROW * 7 / 2
        xor ax, ax
        rep stosw
        pop es
        ret

; AL = program 0..23 -> ES:BX = its record (T_DA04_002B), ZF = 1 if none.
lc_cv_record:
        xor ah, ah
        push ax
        FCALL T_DA04_002B
        add sp, 2
        mov bx, ax
        mov es, dx
        or ax, dx
        ret

; AL = program: ZF = 1 when its 64 note records name no Sound (+0 = FFh).
lc_cv_empty:
        call lc_cv_record
        jz .no
        add bx, 0x3E
        mov cx, 64
.n:     cmp byte [es:bx], 0xFF
        jne .no
        add bx, 0x18
        loop .n
        xor ax, ax                      ; ZF = 1
        ret
.no:    mov al, 1
        or al, al                       ; ZF = 0
        ret

; The first program after the current one whose note records are all empty,
; else the current one + 1.
lc_cv_default:
        mov al, [MUTE_PROGRAM]
        mov cl, MUTE_PROGRAM_COUNT - 1
.try:   inc al
        cmp al, MUTE_PROGRAM_COUNT
        jb .test
        xor al, al
.test:  push ax
        push cx
        call lc_cv_empty
        pop cx
        pop ax
        jz .found
        dec cl
        jnz .try
        mov al, [MUTE_PROGRAM]
        inc al
        cmp al, MUTE_PROGRAM_COUNT
        jb .found
        xor al, al
.found: mov [cs:lc_cv_prog], al
        ret

; SI = cave string -> CS:DI, DI at its 0.
lc_cat: mov al, [cs:si]
        or al, al
        jz .r
        mov [cs:di], al
        inc si
        inc di
        jmp lc_cat
.r:     mov byte [cs:di], 0
        ret

; The page in the framebuffer (glyph rows 0, 8, 16, 24, 32; soft keys 57).
lc_cv_draw:
        push es
        push ds
        pop es
        mov di, FB
        mov cx, ROW * 64 / 2
        xor ax, ax
        rep stosw
        pop es
        xor ax, ax
        xor bx, bx
        mov si, lc_s_title
        call text
        ; Slices:nn  Names:<source>nn
        mov di, lc_line
        mov si, lc_s_slices
        call lc_cat
        xor ax, ax
        mov al, [cs:zones_count]
        mov cx, 2
        call digits
        mov si, lc_s_names
        call lc_cat
        xor bx, bx
.name:  mov al, [cs:zones_identity+bx]
        or al, al
        jz .named
        mov [cs:di], al
        inc di
        inc bx
        cmp bx, 13
        jb .name
.named: dec di                          ; trim trailing spaces
        cmp di, lc_line
        jb .trimmed
        cmp byte [cs:di], ' '
        je .named
.trimmed:
        inc di
        mov word [cs:di], 'nn'
        mov byte [cs:di+2], 0
        mov ax, 8
        xor bx, bx
        mov si, lc_line
        call text
        ; Program:nn-<name>
        mov di, lc_line
        mov si, lc_s_program
        call lc_cat
        xor ax, ax
        mov al, [cs:lc_cv_prog]
        inc ax
        mov cx, 2
        call digits
        mov byte [cs:di], '-'
        inc di
        push di
        mov al, [cs:lc_cv_prog]
        call lc_cv_record
        pop di
        jz .noname
        xor si, si
.pname: mov al, [es:bx+si]
        cmp al, ' '
        jb .noname
        cmp al, 0x7E
        ja .noname
        mov [cs:di], al
        inc di
        inc si
        cmp si, 16
        jb .pname
.noname:mov byte [cs:di], 0
        mov ax, 16
        xor bx, bx
        mov si, lc_line
        call text
        ; Pads: A01-Xnn in slice order
        xor ax, ax
        mov al, [cs:zones_count]
        dec ax
        mov bl, al
        shr al, 4
        add al, 'A'
        mov [cs:lc_s_pads+10], al
        mov al, bl
        and ax, 15
        inc ax
        mov di, lc_s_pads + 11
        mov cx, 2
        call digits
        mov ax, 24
        xor bx, bx
        mov si, lc_s_pads
        call text
        ; Choke slices:ON   (mute group 1)
        mov ax, 32
        xor bx, bx
        mov si, lc_s_choke
        call text
        mov si, mu_off
        cmp byte [cs:lc_cv_choke], 0
        je .onoff
        mov si, mu_on
.onoff: mov di, lc_line
        mov cx, 3
.oo:    mov al, [cs:si]
        mov [cs:di], al
        inc si
        inc di
        loop .oo
        mov byte [cs:di], 0
        mov ax, 32
        mov bx, 13
        mov si, lc_line
        call text
        mov ax, 32
        mov bx, 18
        mov si, lc_s_group
        call text
        mov ax, 57
        xor bx, bx
        mov si, lc_s_doit               ; ENTER, not a soft key
        call text
        mov ax, 57
        mov bx, 32
        mov si, lc_s_cancel
        call text
        mov si, [cs:lc_cv_status]       ; "Stop the sequencer first", "Program nn kept"
        or si, si
        jz .nostatus
        mov ax, 40
        xor bx, bx
        call text
.nostatus:
        ; focus: the program number or the ON/OFF value
        mov bx, 8 * 6
        mov cx, 12
        mov ax, 15
        cmp byte [cs:lc_cv_focus], 0
        je .focus
        mov bx, 13 * 6
        mov cx, 18
        mov ax, 31
.focus: mov dx, 8
        jmp invert

; SI = message: row 40 of the page, one key to acknowledge.  The pads are stock
; while it shows (an error box ends the ownership, spec A10).  AL = 2, or AL = 0
; with BL = the acknowledging key when it is a mode key (lc_convert's return).
lc_message:
        push si
        mov di, FB + ROW * 40
        call lc_clear7
        pop si
        mov ax, 40
        xor bx, bx
        call text
        call fast_blit
        mov byte [cs:lc_owned], 0
        mov byte [cs:lc_cv_boxed], 0
        call lc_key
        mov bl, al
        cmp byte [cs:lc_cv_boxed], 0
        je .owned
        push bx
        FCALL T_C4C8_0F5F               ; a stock error box left the LCD in text mode
        pop bx
.owned: mov al, [cs:zones_valid]
        mov [cs:lc_owned], al
        call lc_flush
        call lc_mode_key
        mov al, 2
        jne .r
        xor al, al                      ; a mode key leaves the view with it
.r:     ret

; <Do it>: the Sounds (the CHOP engine, nothing created on any refusal), then
; the program: stock "Initialize a program" through mute_program_init_hook,
; named after the Source, slice k on slot k-1's note (35..98, first use), choke
; = mute group 1 on every assigned pad, then selected.
lc_cv_run:
        mov di, FB + ROW * 40
        call lc_clear7
        mov ax, 40
        xor bx, bx
        mov si, lc_s_busy
        call text
        call fast_blit
        call lc_disk_scan               ; slice names unique on the selected disk too
        mov byte [cs:chop_naming], 1
        push bp
        mov bp, [cs:page_bp]            ; the suspended Edit Sound page (chop_create_all)
        call chop_create_all
        pop bp
        mov byte [cs:chop_naming], 0
        mov byte [cs:full_ok], 0        ; the session pool held the engine's state
        mov byte [cs:fvalid], 0
        or ax, ax
        jns .made
        mov si, lc_s_short
        cmp ax, CHOP_ERR_SHORT
        je .error
        cmp ax, CHOP_ERR_EMPTY
        je .error
        mov si, lc_s_memory
        cmp ax, -2
        je .error
        mov si, lc_s_records
        cmp ax, -3
        je .error
        mov si, lc_s_failed
.error: call lc_message
        jmp lc_flush                    ; AL, BL kept
.made:  xor cx, cx                      ; the new indices, before anything reuses the pool
        mov cl, [cs:zones_count]
        xor bx, bx
.copy:  mov al, [cs:chop_created+bx]
        mov [cs:lc_cv_sounds+bx], al
        inc bx
        loop .copy
        xor ax, ax
        mov al, [cs:lc_cv_prog]
        push ax
        push cs
        call mute_program_init_hook     ; far frame: [bp+6] = the program
        add sp, 2
        call lc_cv_name                 ; the Source's name, unique among the programs
.select:xor ax, ax
        mov al, [cs:lc_cv_prog]
        push ax
        FCALL T_CA45_0008               ; select program
        add sp, 2
        xor ax, ax
        mov [cs:lc_cv_skipped], al
        mov [cs:lc_used], ax
        mov [cs:lc_used+2], ax
        mov [cs:lc_used+4], ax
        mov [cs:lc_used+6], ax
        xor si, si                      ; SI = slice / slot
.slot:  mov ax, si
        cmp al, [cs:zones_count]
        jae .assigned
        push si
        FCALL T_D9F2_000C               ; slot -> note, the selected program's map
        add sp, 2
        cmp al, 35
        jb .skip
        cmp al, 98
        ja .skip
        sub al, 35
        xor ah, ah
        mov di, ax                      ; DI = note - 35
        mov bx, ax
        shr bx, 3
        mov cl, al
        and cl, 7
        mov al, 1
        shl al, cl
        test [cs:lc_used+bx], al
        jnz .skip
        or [cs:lc_used+bx], al
        mov al, [cs:lc_cv_prog]
        call lc_cv_record
        jz .skip
        mov ax, di
        mov dx, 0x18
        mul dx
        add bx, ax
        mov al, [cs:lc_cv_sounds+si]
        mov [es:bx+0x3E], al            ; note record +0: the Sound
        cmp byte [cs:lc_cv_choke], 0
        je .next
        mov byte [es:bx+0x3E+6], 1      ; Poly: MONO (+6, notes/mute_voice.md): a pad cuts itself
        mov al, [cs:lc_cv_prog]
        mov bx, si
        mov dl, 1
        call mute_set_group             ; mute group 1
        jmp .next
.skip:  inc byte [cs:lc_cv_skipped]
.next:  inc si
        jmp .slot
.assigned:
        cmp byte [cs:lc_cv_choke], 0
        je .report
        mov al, [cs:lc_cv_prog]
        mov dl, 1
        call mute_set_enabled
.report:call lc_flush                   ; pads hit while the sounds were made: not played
        mov al, [cs:lc_cv_skipped]
        or al, al
        jz .done
        xor ah, ah
        mov di, lc_s_skipped + 13
        mov cx, 2
        call digits
        mov si, lc_s_skipped
        call lc_message
        or al, al
        jz .leave
.done:  mov si, lc_s_made               ; "nn sounds, program nn" on row 49
        cmp byte [cs:lc_disk_ok], 0
        jne .said
        mov si, lc_s_made_nd            ; "... (disk not checked)"
.said:  push si
        mov di, si
        xor ax, ax
        mov al, [cs:zones_count]
        mov cx, 2
        call digits
        pop si
        push si
        lea di, [si+19]
        xor ax, ax
        mov al, [cs:lc_cv_prog]
        inc ax
        mov cx, 2
        call digits
        pop si
        call lc_status
        mov al, 2
.leave: ret

; ---------------------------------------------------------------- strings (PMONEY wording)

lc_s_hit:      db "Hit a pad to start", 0
lc_s_cancel:   db "<Cancel>", 0
lc_s_done:     db "<Done>", 0
lc_s_chops:    db "Chops: 00", 0
lc_s_lazy:     db "<Lazy chop>", 0
lc_s_snap_on:  db "<Snap ON>", 0
lc_s_snap_off: db "<SnapOFF>", 0
lc_s_toprog:   db "<To program>", 0
lc_s_bank:     db "Bank A", 0
lc_s_off:      db "Offset:+00ms", 0
lc_s_max:      db "Too many slices (64)", 0
lc_s_title:    db "Slices to Program", 0
lc_s_doit:     db "ENTER:Do it", 0
lc_s_slices:   db "Slices:", 0
lc_s_names:    db "  Names:", 0
lc_s_program:  db "Program:", 0
lc_s_pads:     db "Pads: A01-A01 in slice order", 0
lc_s_choke:    db "Choke slices:", 0
lc_s_group:    db "(mute group 1)", 0
lc_s_replace:  db "Replace program 00?", 0
lc_s_kept:     db "Program kept:   00", 0
lc_s_doreplace:db "<Replace>", 0
lc_s_locked:   db "Stop the sequencer first", 0
lc_s_made:     db "00 sounds, program 00", 0
lc_s_made_nd:  db "00 sounds, program 00 (disk not checked)", 0
lc_s_ask_eq:   db "Equal zones again? Enter: yes", 0
lc_s_lost:     db "Lost:00", 0
lc_s_hint:     db "Chop:>>", 0
lc_s_busy:     db "Making the sounds...", 0
lc_s_short:    db "Slice too short", 0
lc_s_slice_short: db "Slice 00 too short", 0
lc_s_memory:   db "Not enough sound memory", 0
lc_s_records:  db "Not enough sound records", 0
lc_s_failed:   db "Sounds not made", 0
lc_s_skipped:  db "Pads skipped:00 (note)", 0

; ---------------------------------------------------------------- state (RAM in the cave)

lc_owned:      db 0             ; the view owns the pads (with MODE 'L' / OPTION 6)
lc_phase:      db 0             ; 0 Zones / Refine, 1 Armed, 2 Recording
lc_head:       db 0             ; ring: read index (view), write index (ISR)
lc_tail:       db 0
lc_dropped:    db 0             ; hits lost on a full ring
lc_snap:       db 1             ; D4: on
lc_offset:     db 0             ; user offset, ms
lc_nchops:     db 0
lc_dirty:      db 0
lc_note:       db 0             ; the take ended at 64 chops
lc_tune0:      db 0
lc_commit:     db 0             ; move is committing a numeric entry
lc_aud_n:      db 0
lc_aud_ch:     times 4 db 0     ; channels of the view's latest audition
chop_naming:   db 0
lc_cv_prog:    db 0
lc_cv_choke:   db 1
lc_cv_focus:   db 0
lc_cv_typing:  db 0
lc_cv_number:  db 0
lc_cv_skipped: db 0
lc_box:        db 0             ; a stock error box was up: the pads were stock
lc_ask_eq:     db 0             ; "Equal zones again?" open for one key
lc_self_end:   db 0             ; the take ended by itself (Source end, 64 chops)
lc_edit_dirty: db 0             ; a CHOPS slice was stepped and not snapped yet
lc_edit_slice: db 0
lc_bank_shown: db 0
lc_cv_boxed:   db 0             ; lc_key showed a stock error box
lc_cv_stale:   db 0             ; the page's key came within 0.25 s
lc_edit_point: db 0             ; the stepped point: 0 start, 1 end
lc_redraw:     db 0             ; lc_poll redraws before the next key
lc_coal_key:   db 0             ; + or -: the key being coalesced
lc_used:       times 8 db 0     ; notes 35..98 assigned by Convert
lc_line:       times 41 db 0
lc_disk_ok:    db 0             ; lc_disk_scan read the selected disk's directory
lc_find:       times 28 db 0    ; find first / next record (raw name at +7)
lc_taken:      times LC_DISK_N / 8 db 0
align 2
lc_captured:   dw 0             ; raw pads pressed while owned
lc_t0:         dd 0
lc_note_ptr:   dw 0             ; the status lc_row49 shows while lc_note
lc_tick0:      dw 0             ; [D38C] at t0
lc_end_ticks:  dw 0             ; ticks from t0 to the Source end
lc_end_tick:   dw 0             ; [D38C] when a take ended by itself
lc_cv_tick:    dw 0             ; [D38C] when the Convert page or prompt was drawn
lc_cv_status:  dw 0             ; a line on the Convert page (row 40), or 0
lc_name_n:     dw 0
lc_name_len:   dw 0
lc_disk_rc:    dw 0             ; find first's result
lc_k:          dd 0
lc_lo:         dd 0
lc_hi:         dd 0
lc_s:          dd 0
lc_from:       dd 0
lc_ring:       times LC_RING * 8 db 0
lc_chops:      times LC_MAX dd 0   ; the take's chop points (Convert: its Sound indices)
lc_cv_sounds   equ lc_chops
