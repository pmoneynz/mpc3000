; Multi-zone Sound creation for the WAVE Edit Sound extension.
;
; The two hook entries are reached by far JMPs from B99A.  chop_create_all
; is a near helper and deliberately keeps the suspended B99A page BP live.
; All mutable state is CS-relative because the F07D cave is copied to RAM.

%ifdef PROFILE_316
CHOP_MIN_FRAMES equ 1368        ; the shortest Sound stock 3.16 keys on (lazychop316.inc
                                ; LC_MIN, notes/lazy_chop.md §13.5 item 13): CHOP ZONE,
                                ; ZONE->NEW SOUND and Convert make nothing shorter
%else
CHOP_MIN_FRAMES equ 441
%endif
CHOP_ERR_EMPTY equ -0x0101
CHOP_ERR_MAP equ -0x0102
CHOP_ERR_SHORT equ -0x0103
%ifndef CHOP_CAVE_OPTS
 %define CHOP_CAVE_OPTS 0
%endif

; Stock Edit Sound safety (Vailixi profiles, CHOP_HAS_SAFE_LOCK and
; CHOP_HAS_EDIT_MUTE).  Every stock Do handler refuses through B99A:1595
; when [A7AE] (transport state, meaning HYPOTHESIS) and the "safe lock"
; setting [862F] are both non-zero (B99A:0B2F..0B3D).  The copy wrapper
; B99A:1728 mutes through D980:000C while [8629] is set.  OS 3.16 has
; neither setting and never mutes in Edit Sound, so its profile leaves both
; out (notes/port_316.md).

; Replaces B99A:[046D,048F).  The stock choice field (CHOP_STOCK_OPTIONS
; entries) is rebuilt with CHOP ZONE appended.  Width remains 16 characters.
chop_do_field:
        cmp byte [CHOP_DO], CHOP_STOCK_OPTIONS+1
        jb .index_ok
        mov byte [CHOP_DO], 0
.index_ok:
        push 16
        PUSH_CAVE_SEG
        push chop_do_options
        push ds
        push CHOP_DO
        push ds
        push CHOP_DO_LABEL
        FCALL T_B354_01C6
        add sp, 14
        FJMP T_B99A_048F

; Replaces B99A:[0AFF,0B0D).  Stock values rejoin the stock jump table;
; value CHOP_STOCK_OPTIONS creates all mapped zones, refreshes the page's
; sound list, and reports a negative result through the stock error path.
chop_do_dispatch:
        mov al, [CHOP_DO]
        xor ah, ah
        mov bx, ax
        cmp bx, CHOP_STOCK_OPTIONS-1
        jbe .stock
        cmp bx, CHOP_STOCK_OPTIONS
        jne .leave
%ifdef CHOP_HAS_SAFE_LOCK
        ; The stock handlers' safe-lock refusal, before any state is touched.
        cmp byte [CHOP_SEQ_STATE], 0
        je .unlocked
        cmp byte [CHOP_SAFE_LOCK], 0
 %ifdef CHOP_SETTINGS_INVERTED
        je .leave                       ; 3.16 stores the setting inverted: 0 = ON
 %else
        jne .leave
 %endif
.unlocked:
%endif
        ; Keep the page's current selection even when an old map is rejected.
        ; zones_source may belong to a different sound on this error path.
        xor ax, ax
        mov al, [ss:bp-2]
        lea si, [bp-0x0BC]
        add si, ax
        mov al, [ss:si]
        mov [cs:chop_selected_record], al
        call chop_create_all
        or ax, ax
        jns .refresh
        cmp ax, CHOP_ERR_EMPTY
        je .empty_zone
        cmp ax, CHOP_ERR_MAP
        je .stale_map
        cmp ax, CHOP_ERR_SHORT
        je .short_zone
        mov si, ax
        FCALL T_B1B1_004F
        neg si
        push si
        FCALL T_B3C7_0007
        add sp, 2
        FCALL T_B1B1_0055
        jmp .refresh
.empty_zone:
        mov si, chop_empty_text
        call chop_show_status
        jmp .refresh
.stale_map:
        mov si, chop_stale_text
        call chop_show_status
        jmp .refresh
.short_zone:
        mov si, chop_short_text
        call chop_show_status
.refresh:
        push 0
        push ss
        lea ax, [bp-0x2C0]
        push ax
        push ss
        lea ax, [bp-0x0BC]
        push ax
        FCALL T_B99A_27F2
        add sp, 10
        ; Allocation fills the lowest free record, so rebuilding the sorted
        ; list can shift the selection. Find the previous record before redraw uses
        ; [BP-2] as the selected list position.  Like stock B99A:04E9, also
        ; save it as the word global read by the next page entry; positions
        ; are 0..127 (B99A:282A), so BX equals stock's CBW form.
        or ax, ax
        jle .redraw
        mov cx, ax
        lea si, [bp-0x0BC]
        xor bx, bx
.find_source:
        mov dl, [ss:si]
        xor dh, dh
        cmp dl, [cs:chop_selected_record]
        je .source_found
        inc si
        inc bx
        loop .find_source
        jmp .redraw
.source_found:
        mov [bp-2], bl
        mov [LIST_SELECTION], bx
.redraw:
        FCALL T_B99A_16BB
.leave: FJMP T_B99A_1595
.stock:
%ifdef CHOP_LOCK_STOCK
        ; Vailixi's per-handler safe lock (B99A:0B2F..0B3D in every Do
        ; handler; their preambles before it only read), for 3.16's stock
        ; handlers and the cave's two.
        cmp byte [CHOP_SEQ_STATE], 0
        je .stock_unlocked
        cmp byte [CHOP_SAFE_LOCK], 0
        je .leave                       ; inverted: 0 = ON
.stock_unlocked:
%endif
        mov byte [cs:zones_valid], 0
        mov byte [cs:zones_resume], 0
%ifdef CHOP_EDITDO
        mov bl, [cs:editdo_map+bx]      ; list index -> 3.16 handler 0..7, or 80h/81h
        or bl, bl
        js editdo_run
%endif
        FJMP T_B99A_0B0D

%ifdef CHOP_EDITDO
; Vailixi 3.50's two extra Edit Sound Do options on a stock list without
; them (OS 3.16).  Entered from chop_do_dispatch with BL = 80h (COPY ZONE->
; SND, Vailixi B99A:0B92) or 81h (TRUNC SFT ST+END, Vailixi B99A:121C).
; BP = the suspended Edit Sound frame, [BP-1] = 0, DI = the page's sound
; count (never written here), SS:SP at the page's level, DS = DGROUP.
editdo_run:
        cmp bl, 0x81
        je editdo_trunc
        ; Vailixi B99A:0B92..0BAB: nothing unless zone end > zone start
        ; (high words signed, low words unsigned).
        mov dx, [ZONE_EN+2]             ; DX: CMP AX,[disp16] would encode 3B 06,
        cmp dx, [ZONE_ST+2]             ; a word equal to segment 063B
        jg .zone_ok
        jl .leave
        mov dx, [ZONE_EN]
        cmp dx, [ZONE_ST]
        jbe .leave
.zone_ok:
        xor ax, ax
        mov al, [ss:bp-2]
        lea si, [bp-0x0BC]
        add si, ax
        mov al, [ss:si]
        mov [cs:chop_selected_record], al
        call editdo_copy
        or ax, ax
        jns .refresh
        cmp ax, CHOP_ERR_SHORT
        jne .stock_error
        mov si, chop_short_text
        call chop_show_status
        jmp .refresh
.stock_error:
        mov si, ax                      ; Vailixi B99A:0BEE..0C03
        FCALL T_B1B1_004F
        neg si
        push si
        FCALL T_B3C7_0007
        add sp, 2
        FCALL T_B1B1_0055
.refresh:
        jmp chop_do_dispatch.refresh    ; rebuild list, reselect source, redraw
.leave: FJMP T_B99A_1595

; TRUNC SFT ST+END = Vailixi B99A:122D..124E (delete [Soft end, Length))
; followed by its DEL BEFR SOFT ST code, which on 3.16 is the stock handler
; 0B72:0DFF: delete [0, Soft start), reload the page caches, print Length,
; clamp Zone end, redraw, leave.  Page caches (dwords, low word first):
; [BP-28h] Soft start, [BP-2Ch] Soft end, [BP-30h] Length.
editdo_trunc:
        push word [bp-0x2E]
        push word [bp-0x30]
        push word [bp-0x2A]
        push word [bp-0x2C]
        xor ax, ax
        mov al, [ss:bp-2]
        lea bx, [bp-0x0BC]
        add bx, ax
        mov al, [ss:bx]
        push ax
        FCALL T_B99A_22C4
        add sp, 10
        FJMP T_B99A_0FA9

; COPY ZONE-> SND engine: Vailixi B99A:1728 with mode 1, on 3.16's own
; allocator and copy.  In: chop_selected_record, ZONE_ST, ZONE_EN.  Out: AX =
; 0, an allocator result (-1 name, -2 memory, -3 records) or CHOP_ERR_SHORT.
; Preserves SI, DI, BP, DS.
editdo_copy:
        push si
        push di
        push es
        mov ax, [ZONE_ST]
        mov dx, [ZONE_ST+2]
        mov [cs:chop_start], ax
        mov [cs:chop_start+2], dx
        mov ax, [ZONE_EN]
        mov dx, [ZONE_EN+2]
        sub ax, [cs:chop_start]
        sbb dx, [cs:chop_start+2]
        mov [cs:chop_count], ax
        mov [cs:chop_count+2], dx
        ; PMONEY rule (not Vailixi): below 441 frames D0C0:0611 records 441
        ; but allocates fewer words; refuse as CHOP ZONE does.
        or dx, dx
        jnz .long_enough
        cmp ax, CHOP_MIN_FRAMES
        jae .long_enough
        mov ax, CHOP_ERR_SHORT
        jmp .return_unmuted
.long_enough:
        mov al, 1                       ; Vailixi B99A:1732: mute at entry
        call chop_mute
%ifdef CHOP_REBUILD_FIRST
        FCALL T_D0C0_086F               ; Vailixi rebuilds at page entry (B99A:0024)
%endif
        ; Vailixi B99A:1755..1773: delete TEMPORARY999 if it exists.  PMONEY
        ; keeps it when it is the source (Vailixi would delete the source).
        push ds
        push EDITDO_TEMP_NAME
        FCALL T_D0C0_0D17
        add sp, 4
        or ax, ax
        js .no_temp
        cmp al, [cs:chop_selected_record]
        je .no_temp
        push 1
        push 0
        push ax
        FCALL T_D0C0_0B19
        add sp, 6
.no_temp:
        call chop_make_name             ; Vailixi C6C2:173D(name, 1): ZONEnnn
        call editdo_source_record
        xor ax, ax
        mov al, [es:bx+0x13]
        mov [cs:chop_source_stereo], al
        push ax
        push word [cs:chop_count+2]
        push word [cs:chop_count]
        PUSH_CAVE_SEG
        push chop_name
        FCALL T_D0C0_0611
        add sp, 10
        mov [cs:chop_dest_index], ax
        mov al, 7                       ; Vailixi B99A:1801..1816
        mov bx, editdo_copying_text
        call du_row_put
        call du_eol
        mov ax, [cs:chop_dest_index]
        or ax, ax
        jns .allocated
        call editdo_softkeys            ; Vailixi B99A:1830..184B
        mov ax, [cs:chop_dest_index]
        jmp .return
.allocated:
        call snd_record
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        mov [cs:chop_dest], ax
        mov [cs:chop_dest+2], dx
        ; Source base after allocation: D0C0:0611 may have compacted.
        call editdo_source_record
        mov ax, [es:bx+0x1C]
        mov dx, [es:bx+0x1E]
        mov [cs:chop_source_len], ax
        mov [cs:chop_source_len+2], dx
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        add ax, [cs:chop_start]
        adc dx, [cs:chop_start+2]
        mov [cs:chop_src], ax
        mov [cs:chop_src+2], dx
        call chop_copy_plane            ; Vailixi B99A:184F..189E
        cmp byte [cs:chop_source_stereo], 1
        jne .copied
        mov ax, [cs:chop_source_len]    ; Vailixi B99A:18BB..1925
        mov dx, [cs:chop_source_len+2]
        add [cs:chop_src], ax
        adc [cs:chop_src+2], dx
        mov ax, [cs:chop_count]         ; = new record +1C (>= 441 frames)
        mov dx, [cs:chop_count+2]
        add [cs:chop_dest], ax
        adc [cs:chop_dest+2], dx
        call chop_copy_plane
.copied:
        FCALL T_D0C0_086F               ; Vailixi B99A:1928
        call editdo_softkeys            ; Vailixi B99A:192D..1942
        xor ax, ax
.return:
        push ax                         ; Vailixi B99A:181F / 1945: unmute on both exits
        mov al, 0
        call chop_mute
        pop ax
.return_unmuted:
        pop es
        pop di
        pop si
        ret

; ES:BX = record of chop_selected_record.  Clobbers AX, DX.
editdo_source_record:
        xor ax, ax
        mov al, [cs:chop_selected_record]
        jmp snd_record

; Bottom row back to the stock soft keys.
editdo_softkeys:
        mov al, 7
        call du_at
        mov bx, EDITDO_SOFTKEYS
        jmp du_put_ds
%endif

; Lifecycle hook for D0C0:[0B19,0B1F).  It recreates the replaced
; prologue, invalidates a map before its source record is deleted, and then
; rejoins the original routine.  AX is dead at the rejoin point.
chop_sound_delete:
        push bp
        mov bp, sp
        sub sp, 6
        mov ax, [bp+6]
        cmp ax, [cs:zones_source]
        jne .keep
        mov byte [cs:zones_valid], 0
.keep:  FJMP T_D0C0_0B1F

; Create one collision-safe ZONE Sound for every [B[i],B[i+1]) interval.
; Returns AX=0, or a negative stock-style error.  The operation preflights
; descriptor identity, exact boundaries, free records and free wave words.
; Allocator failures roll back every record created by this invocation.
chop_create_all:
        push bx
        push cx
        push dx
        push si
        push di
        push ds
        push es
        mov word [cs:chop_result], CHOP_ERR_MAP
        mov byte [cs:chop_created_count], 0

        cmp byte [cs:zones_valid], 1
        jne .return
        xor cx, cx
        mov cl, [cs:zones_count]
        cmp cx, 1
        jb .return
        cmp cx, ZONE_MAX
        ja .return
        xor ax, ax
        mov al, [cs:zones_current]
        cmp ax, 1
        jb .return
        cmp ax, cx
        ja .return

        ; Resolve the page's live selected-sound index.  A map made for a
        ; previously selected record must never be applied to the new one.
        xor ax, ax
        mov al, [ss:bp-2]
        mov bx, bp
        sub bx, 0x0BC
        add bx, ax
        mov al, [ss:bx]
        xor ah, ah
        cmp ax, [cs:zones_source]
        jne .return

        ; Recheck the source identity saved by zones_enter: name, stereo,
        ; length and base.  The base is refreshed after our own allocations.
        call chop_source_record
        xor si, si
.name_identity:
        mov al, [es:bx+si]
        cmp al, [cs:zones_identity+si]
        jne .return
        inc si
        cmp si, 16
        jb .name_identity
        mov al, [es:bx+0x13]
        cmp al, [cs:zones_identity+16]
        jne .return
        cmp al, 1
        ja .return
        xor si, si
.tail_identity:
        mov al, [es:bx+si+0x1C]
        cmp al, [cs:zones_identity+si+17]
        jne .return
        inc si
        cmp si, 8
        jb .tail_identity
        mov al, [es:bx+0x13]
        mov [cs:chop_source_stereo], al
        mov al, [es:bx+0x11]
        mov [cs:chop_source_volume], al
        mov al, [es:bx+0x12]
        mov [cs:chop_source_tune], al
        mov ax, [es:bx+0x1C]
        mov dx, [es:bx+0x1E]
        mov [cs:chop_source_len], ax
        mov [cs:chop_source_len+2], dx

        ; Import any stock Edit Sound changes made to the active pair since
        ; leaving the waveform view.  Identity and current/count bounds have
        ; already been checked, so zones_offset cannot escape the table.
        call zones_import
        push cx
        call chop_sync_zone_fields      ; the page shows the imported pair
        pop cx

        ; The editable domain is [B[0],B[N]] within the source.  Every
        ; interval must be positive and at least 441 frames.  D0C0:0611
        ; allocates a smaller caller count but clamps record +1C to 441; the
        ; stock SND loader repeats that mismatch on reload, so shorter exact
        ; Sounds are not persistent-safe without a separate loader patch.
%ifdef PROFILE_316
        mov ax, [cs:zones_pairs]
        mov dx, [cs:zones_pairs+2]
%else
        mov ax, [cs:zones_bounds]
        mov dx, [cs:zones_bounds+2]
%endif
        cmp dx, [cs:chop_source_len+2]
        ja .return
        jb .first_in_range
        cmp ax, [cs:chop_source_len]
        ja .return
.first_in_range:
        mov word [cs:chop_required], 0
        mov word [cs:chop_required+2], 0
        xor si, si
.validate_zone:
        mov bx, si
%ifdef PROFILE_316
        shl bx, 3                       ; pair i: {start, end} at [bx], [bx+4]
        add bx, zones_pairs
%else
        shl bx, 1
        shl bx, 1
        add bx, zones_bounds
%endif
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        cmp dx, [cs:bx+2]
        jb .empty
        ja .positive_zone
        cmp ax, [cs:bx]
        jbe .empty
.positive_zone:
        sub ax, [cs:bx]
        sbb dx, [cs:bx+2]
        cmp dx, 0
        jne .zone_long_enough
        cmp ax, CHOP_MIN_FRAMES
        jb .short
.zone_long_enough:
        cmp byte [cs:chop_source_stereo], 0
        je .add_required
        shl ax, 1
        rcl dx, 1
.add_required:
        add [cs:chop_required], ax
        adc [cs:chop_required+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        cmp dx, [cs:chop_source_len+2]
        ja .return
        jb .end_in_range
        cmp ax, [cs:chop_source_len]
        ja .return
.end_in_range:
        inc si
        cmp si, cx
        jb .validate_zone

%ifdef CHOP_REBUILD_FIRST
        ; 3.16 rebuilds allocation extents only after its own operations,
        ; not at Edit Sound entry as Vailixi does (B99A:0024).
        FCALL T_D0C0_086F
%endif
        FCALL T_D0C0_084D
        xor dx, dx
        mov dl, [cs:zones_count]
        cmp ax, dx
        jae .slots_ok
        mov word [cs:chop_result], -3
        jmp .return
.slots_ok:
        FCALL T_D0C0_0236
        cmp dx, [cs:chop_required+2]
        jb .no_memory
        ja .resources_ok
        cmp ax, [cs:chop_required]
        jae .resources_ok
.no_memory:
        mov word [cs:chop_result], -2
        jmp .return

.resources_ok:
        ; Read-only preflight passed.  Mute as stock B99A:1732 does before
        ; any naming, allocation or wave-memory work; both exits unmute.
        mov al, 1
        call chop_mute
        mov byte [cs:chop_zone], 0
.create_zone:
        xor bx, bx
        mov bl, [cs:chop_zone]
%ifdef PROFILE_316
        shl bx, 3
        add bx, zones_pairs
%else
        shl bx, 1
        shl bx, 1
        add bx, zones_bounds
%endif
        mov ax, [cs:bx]
        mov dx, [cs:bx+2]
        mov [cs:chop_start], ax
        mov [cs:chop_start+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        sub ax, [cs:bx]
        sbb dx, [cs:bx+2]
        mov [cs:chop_count], ax
        mov [cs:chop_count+2], dx

%ifdef PROFILE_316
        call chop_name_slice            ; ZONEnnn, or Lazy Chop's <source>nn (lazychop316.inc)
%elifdef CHOP_OWN_NAMES
        call chop_make_name
%else
        push 1
        PUSH_CAVE_SEG
        push chop_name
        FCALL T_C6C2_173D
        add sp, 6
%endif

        xor ax, ax
        mov al, [cs:chop_source_stereo]
        push ax
        push word [cs:chop_count+2]
        push word [cs:chop_count]
        PUSH_CAVE_SEG
        push chop_name
        FCALL T_D0C0_0611
        add sp, 10
        or ax, ax
        js .rollback
        mov [cs:chop_dest_index], ax

        ; Fetch both bases after allocation.  D0C0:0611 may compact wave RAM
        ; and move the source before returning.
%ifdef PROFILE_316
        call snd_record
%else
        mov dx, 0x24
        mul dx
        add ax, SND_DIR
        mov bx, ax
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
%endif
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        mov [cs:chop_dest], ax
        mov [cs:chop_dest+2], dx
        mov al, [cs:chop_source_volume]
        mov [es:bx+0x11], al
        mov al, [cs:chop_source_tune]
        mov [es:bx+0x12], al
        ; The allocator already owns exactly chop_count words per plane.  Its
        ; later 441 clamp changes only record +1C; restore the exact logical
        ; length and matching end before exposing the new Sound.
        mov ax, [cs:chop_count]
        mov dx, [cs:chop_count+2]
        mov [es:bx+0x1C], ax
        mov [es:bx+0x1E], dx
        sub ax, 1
        sbb dx, 0
        mov [es:bx+0x18], ax
        mov [es:bx+0x1A], dx
        ; No far call occurs between allocator return and the exact descriptor
        ; correction above.  Record the index now so later failures roll it
        ; back.
        xor bx, bx
        mov bl, [cs:chop_created_count]
        mov ax, [cs:chop_dest_index]
        mov [cs:chop_created+bx], al
        inc byte [cs:chop_created_count]
        call chop_source_record
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        add ax, [cs:chop_start]
        adc dx, [cs:chop_start+2]
        mov [cs:chop_src], ax
        mov [cs:chop_src+2], dx
        call chop_copy_plane

        cmp byte [cs:chop_source_stereo], 0
        je .next_zone
        mov ax, [cs:chop_source_len]
        mov dx, [cs:chop_source_len+2]
        add [cs:chop_src], ax
        adc [cs:chop_src+2], dx
        mov ax, [cs:chop_count]
        mov dx, [cs:chop_count+2]
        add [cs:chop_dest], ax
        adc [cs:chop_dest+2], dx
        call chop_copy_plane

.next_zone:
        inc byte [cs:chop_zone]
        mov al, [cs:chop_zone]
        cmp al, [cs:zones_count]
        jb .create_zone
        mov word [cs:chop_result], 0
        jmp .rollback_done

.rollback:
        mov [cs:chop_result], ax
.rollback_one:
        cmp byte [cs:chop_created_count], 0
        je .rollback_done
        dec byte [cs:chop_created_count]
        xor bx, bx
        mov bl, [cs:chop_created_count]
        xor ax, ax
        mov al, [cs:chop_created+bx]
        push 1
        push 0
        push ax
        FCALL T_D0C0_0B19
        add sp, 6
        jmp .rollback_one
        ; Success and rollback share this tail.  Stock unmutes after its
        ; final 086F on success (B99A:1945) and directly after a failed
        ; allocation (B99A:181F); every post-mute exit passes here.
.rollback_done:
        FCALL T_D0C0_086F
        call chop_refresh_source_base
        mov al, 0
        call chop_mute

.return:
        pop es
        pop ds
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        mov ax, [cs:chop_result]
        ret

.empty:
        mov word [cs:chop_result], CHOP_ERR_EMPTY
        jmp .return

.short:
        mov word [cs:chop_result], CHOP_ERR_SHORT
        jmp .return

; The page's zone triples ([BP-0Ch], [BP-12h]) from ZONE_ST/EN, BP = page.
; zones_import may clamp the pair; without this the page shows the old pair
; while a stock Do (DELETE ZONE ...) acts on the new one.
chop_sync_zone_fields:
        mov ax, [ZONE_ST]
        mov dx, [ZONE_ST+2]
        lea bx, [bp-0x0C]
        call numeric_store_components
        mov ax, [ZONE_EN]
        mov dx, [ZONE_EN+2]
        lea bx, [bp-0x12]
        jmp numeric_store_components

; ES:BX = source sound record.  Clobbers AX, DX.
chop_source_record:
        mov ax, [cs:zones_source]
%ifdef PROFILE_316
        jmp snd_record
%else
        mov dx, 0x24
        mul dx
        add ax, SND_DIR
        mov bx, ax
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        ret
%endif

; Keep the map identity and waveform cache coherent if allocation compacted
; the source.  Name, stereo and length are already unchanged and validated.
chop_refresh_source_base:
        call chop_source_record
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        mov [cs:zones_identity+21], ax
        mov [cs:zones_identity+23], dx
        mov [cs:wbase], ax
        mov [cs:wbase+2], dx
        ret

; AL = 1 mutes, 0 unmutes, only while the stock "Mute audio during EDIT SND
; processes" setting is on.  D980:000C writes port 6A and clobbers AL.
chop_mute:
%ifdef CHOP_HAS_EDIT_MUTE
        cmp byte [CHOP_MUTE_EDIT], 0
 %ifdef CHOP_SETTINGS_INVERTED
        jne .done                       ; 3.16: 0 = ON
        call xp_audio                   ; xparams316.inc: Vailixi D980:000C in the cave
 %else
        je .done
        cbw
        push ax
        FCALL T_D980_000C
        add sp, 2
 %endif
%endif
.done:  ret

%ifdef CHOP_OWN_NAMES
; Stock 3.16 can only name "soundNNN" (1849:173F takes no mode), so build
; "ZONEnnn" + 9 spaces in chop_name: the next counter value whose name
; T_D0C0_0D17 does not find (index >= 0 found, -4 free).  At most 128
; Sounds exist, so a free name is reached well within 1000 tries.
; Preserves BX, CX, SI, DI.
chop_make_name:
        push bx
        push cx
        push di
%ifdef PROFILE_316
        ; the whole "ZONE000" + 9 spaces template: chop_name also holds Lazy
        ; Chop's slice names (lazychop316.inc chop_name_slice)
        mov word [cs:chop_name], 'ZO'
        mov word [cs:chop_name+2], 'NE'
        mov bx, 7
.blank: mov byte [cs:chop_name+bx], ' '
        inc bx
        cmp bx, 16
        jb .blank
        mov byte [cs:chop_name+16], 0
%endif
        mov word [cs:chop_name_tries], 1000
.try:   mov ax, [cs:chop_name_counter]
        cmp ax, 999
        jbe .format
        xor ax, ax
.format:
        mov dx, ax
        inc dx
        mov [cs:chop_name_counter], dx
        mov di, chop_name+4
        mov cx, 3
        call digits
        push cs
        push chop_name
        FCALL T_D0C0_0D17
        add sp, 4
        or ax, ax
        js .free
        dec word [cs:chop_name_tries]
        jnz .try
.free:  pop di
        pop cx
        pop bx
        ret
%endif

chop_copy_plane:
        push word [cs:chop_count+2]
        push word [cs:chop_count]
        push word [cs:chop_dest+2]
        push word [cs:chop_dest]
        push word [cs:chop_src+2]
        push word [cs:chop_src]
        FCALL T_D0C0_0E50
        add sp, 12
        ret

; SI = cave string.  Use the stock save/restore pair and bottom-row cursor;
; one normalized key acknowledges the message, matching the stock modal
; error interaction without assigning a false allocator error number.
chop_show_status:
        push si
        FCALL T_B1B1_004F
        push 0
        push 7
        FCALL T_B1B1_0026
        add sp, 4
        pop si
        PUSH_CAVE_SEG
        push si
        FCALL T_B1B1_005B
        add sp, 4
%ifdef PROFILE_316
        call du_eol                     ; clear the soft-key text behind the message
%endif
        push 0
        FCALL T_BDE3_000E
        add sp, 2
        FCALL T_B1B1_0055
        ret

; Far string pointers: offset word, then its segment word.
align 2
chop_do_options:
%assign CHOP_I 0
%rep CHOP_STOCK_OPTIONS
        dw CHOP_OPT_%[CHOP_I]
 %if (CHOP_CAVE_OPTS >> CHOP_I) & 1
        dw CAVE_SEG
 %else
        dw DGROUP_SEG
 %endif
        RELOC_PREV
%assign CHOP_I CHOP_I+1
%endrep
        dw chop_do_text
        dw CAVE_SEG
        RELOC_PREV
        dd 0
chop_do_text: db "CHOP ZONE", 0
%ifdef CHOP_EDITDO
; PMONEY's own wording for the two ported options (16-character list width).
editdo_copy_text: db "ZONE->NEW SOUND ", 0              ; Vailixi's COPY ZONE-> SND
editdo_trunc_text: db "CROP SOFT ST-END", 0             ; Vailixi's TRUNC SFT ST+END
editdo_copying_text: db "Copying zone to a new sound...", 0   ; du_eol blanks to column 40
editdo_map: db 0, 0x80, 1, 2, 3, 4, 5, 0x81, 6, 7    ; list index -> 3.16 handler
%endif
%ifdef PROFILE_316                      ; chop_show_status blanks the row (du_eol)
chop_empty_text: db "EMPTY ZONE - ADJUST BOUNDARIES", 0
chop_stale_text: db "REOPEN WAVE VIEW FOR THIS SOUND", 0
chop_short_text: db "ZONE MUST BE AT LEAST 31ms", 0
%else                                   ; padded to 40 columns over the soft-key row
chop_empty_text: db "EMPTY ZONE - ADJUST BOUNDARIES          ", 0
chop_stale_text: db "REOPEN WAVE VIEW FOR THIS SOUND         ", 0
chop_short_text: db "ZONE MUST BE AT LEAST 10ms              ", 0
%endif

%ifdef PROFILE_316                     ; one Do dispatch: the session pool (mute_storage.inc)
chop_result          equ cave_pool
chop_dest_index      equ cave_pool + 2
chop_source_len      equ cave_pool + 4
chop_required        equ cave_pool + 8
chop_start           equ cave_pool + 12
chop_count           equ cave_pool + 16
chop_src             equ cave_pool + 20
chop_dest            equ cave_pool + 24
chop_source_stereo   equ cave_pool + 28
chop_source_volume   equ cave_pool + 29
chop_source_tune     equ cave_pool + 30
chop_zone            equ cave_pool + 31
chop_created_count   equ cave_pool + 32
chop_selected_record equ cave_pool + 33
chop_created         equ cave_pool + 34
%else
align 2
chop_result: dw 0
chop_dest_index: dw 0
chop_source_len: dd 0
chop_required: dd 0
chop_start: dd 0
chop_count: dd 0
chop_src: dd 0
chop_dest: dd 0
chop_source_stereo: db 0
chop_source_volume: db 0
chop_source_tune: db 0
chop_zone: db 0
chop_created_count: db 0
chop_selected_record: db 0
chop_created: times ZONE_MAX db 0
%endif
%ifdef CHOP_OWN_NAMES
chop_name: db "ZONE000         ", 0      ; 16 characters, digits at +4
align 2
chop_name_counter: dw 0
chop_name_tries: dw 0
%else
chop_name: times 17 db 0
%endif
