; MUTE GROUPS note-on and voice-allocation backend.
;
; Hook sites (both generic Vailixi 3.50 and the 2026-10-01 capture):
;   linear 4FBD3, CFB3:00A3  CALLF CFC6:0007 -> mute_note_on_wrapper
;   linear 507AC, CFC6:0B4C  CALLF CF37:0002 -> mute_voice_alloc_wrapper
;
; Both wrappers are far cdecl routines.  The storage API is in the same
; F07D cave and is called near:
;   mute_get_enabled: AL=program 0..23 -> AL=0/1
;   mute_get_group:   AL=program, BL=canonical pad 0..63 -> AL=0..4
; These APIs preserve SI, DI, BP, and DS.

MUTE_PROGRAM_COUNT equ 24
MUTE_PAD_COUNT     equ 64
MUTE_VOICE_COUNT   equ 32

; Wrap the shared note-on engine so every layer and stereo plane inherits
; one canonical (program, pad) context.  The incoming group is also cached
; for this trigger, while candidate groups are looked up during each choke
; scan so UI edits apply to voices that are already sounding.
;
; The context lives only in this wrapper's own BP frame, on the stack of the
; task that took the trigger.  CFB3:0008 is reached from AMX task 3
; (EAD0:000B) as well as from the shared event pump, and CFC6:0B2D can block
; in the AMX resource reserve D1F7:0126; a CS-global context would therefore
; be visible to, and restorable by, the wrong task.  The allocator wrapper
; finds this frame through the stock BP chain instead.
;   [bp-4] valid   [bp-3] program   [bp-2] pad   [bp-1] group
mute_note_on_wrapper:
        push bp
        mov bp, sp
        xor ax, ax
        push ax                          ; pad = group = 0
        push ax                          ; valid = program = 0

        mov al, [MUTE_CURRENT_PROGRAM]
        cmp al, MUTE_PROGRAM_COUNT
        jae .forward
        mov [bp-3], al
        les bx, [bp+6]                   ; far pointer to the stock event
        mov al, [es:bx+2]                ; MIDI note, 23h..62h for pads
        xor ah, ah
        push ax
        FCALL T_D9F2_003D                ; first pad slot mapped to note
        add sp, 2
        cmp ax, MUTE_PAD_COUNT
        jae .forward
        mov [bp-2], al
        mov byte [bp-4], 1

        mov al, [bp-3]
        call mute_get_enabled
        or al, al
        jz .forward                      ; still tag mapped voices while disabled
        mov bl, [bp-2]
        mov al, [bp-3]
        call mute_get_group
        cmp al, 1
        jb .forward
        cmp al, 4
        ja .forward
        mov [bp-1], al

.forward:
        push word [bp+8]                 ; event segment
        push word [bp+6]                 ; event offset
        FCALL T_CFC6_0007
.builder_return:                         ; frame signature; see below
        leave                            ; also drops the two arguments
        retf

; Wrap the sole stock voice allocator call.  Before each layer/plane is
; allocated, stop every tagged channel belonging to another pad in the same
; program whose current group matches the incoming group.  Same-pad channels
; are left to the stock retrigger, Poly, and Cutoff machinery.  Every mapped
; allocation is tagged even while MUTE GROUPS is disabled or its pad is Off;
; this lets a later enable/group edit act on voices that are still sounding.
; An unmapped/audition allocation clears any older tag on the returned channel.
;
; Every path from mute_note_on_wrapper to this call is exactly three stock
; BP frames deep, in both profiles: CFC6:0007 -> CFC6:039E (01F0/0263/02CC)
; -> CFC6:0B2D (0A8A/0AEC/0B16) -> here.  Each has a push bp/mov bp,sp
; prologue and writes BP nowhere else.  The context is valid only when the
; third frame returns to mute_note_on_wrapper.builder_return in this CS;
; any other caller of 0007/039E (CFC6:0C68, Edit Sound CFC6:0CE9/0C70, the
; WAVE audition) leaves it zero.  Only SS reads; no global is consulted.
;   [bp-2] valid   [bp-1] program   [bp-4] pad   [bp-3] group
mute_voice_alloc_wrapper:
        push bp
        mov bp, sp
        xor ax, ax                       ; AL valid, AH program
        xor dx, dx                       ; DL pad, DH group
        mov bx, [bp]                     ; CFC6:0B2D frame
        mov bx, [ss:bx]                  ; CFC6:039E frame
        mov bx, [ss:bx]                  ; CFC6:0007 frame
        cmp word [ss:bx+2], mute_note_on_wrapper.builder_return
        jne .context
        mov cx, cs
        cmp [ss:bx+4], cx
        jne .context
        mov bx, [ss:bx]                  ; mute_note_on_wrapper frame
        mov ax, [ss:bx-4]
        mov dx, [ss:bx-2]
.context:
        push ax
        push dx
        push si
        push di
        mov [cs:mute_context_valid], ax  ; observer mirror only; never read
        mov [cs:mute_context_pad], dx

        cmp byte [bp-3], 1
        jb .allocate
        xor di, di
.scan:
        mov al, [bp-1]
        inc al                           ; stored program tag is 1..24
        cmp byte [cs:mute_voice_program+di], al
        jne .next
        mov al, [cs:mute_voice_pad+di]
        cmp al, [bp-4]
        je .next
        mov bl, al                       ; candidate's current group, not old group
        mov al, [bp-1]
        call mute_get_group
        cmp al, [bp-3]
        jne .next
        mov byte [cs:mute_voice_program+di], 0
        mov byte [cs:mute_voice_pad+di], 0
        push di
        FCALL T_D21F_0008               ; stock one-channel stop primitive
        add sp, 2
.next:
        inc di
        cmp di, MUTE_VOICE_COUNT
        jb .scan

.allocate:
        ; AMX resource 1 does not nest: a reserve by its owner is a no-op and
        ; the owner's release frees it (Vailixi FB81:0089/00C7, 3.16
        ; 4840:0083/00C1).  D21F:0008 reserves and releases around itself, so
        ; every channel stop made while CFC6:0B2D holds the lock (taken at
        ; 0B30) drops it.  Take it back before the allocator; if it is still
        ; ours this call changes nothing.
        FCALL T_D1F7_0126
        push word [bp+0x0E]             ; channel excluded from voice steal
        push word [bp+0x0C]             ; Cutoff note 2
        push word [bp+0x0A]             ; Cutoff note 1
        push word [bp+0x08]             ; owner/source note
        push word [bp+0x06]             ; Poly enum
        FCALL T_CF37_0002
        add sp, 10
        push ax                         ; the allocator's own MONO/Cutoff
        FCALL T_D1F7_0126               ; stops can drop the lock again; hold
        pop ax                          ; it for the tags and 0B2D's start

        cmp ax, MUTE_VOICE_COUNT
        jae .done                       ; defensive: stock normally returns 0..31
        mov bx, ax
        cmp byte [bp-2], 1
        jne .clear
        mov dl, [bp-1]
        inc dl                           ; program tag 1..24; zero is invalid
        mov [cs:mute_voice_program+bx], dl
        mov dl, [bp-4]
        mov [cs:mute_voice_pad+bx], dl
        jmp .done
.clear:
        mov byte [cs:mute_voice_program+bx], 0
        mov byte [cs:mute_voice_pad+bx], 0
.done:
        pop di
        pop si
        leave
        retf

; Invalidate voice tags before a program record is initialized or a copy
; overwrites the destination.  Sounding channels are not stopped; they simply
; cease to participate in later mute-group decisions for the old record.
; Near ABI: AL=program 0..23; preserves SI, DI, BP, and DS.
mute_forget_program:
        cmp al, MUTE_PROGRAM_COUNT
        jae .return
        inc al                           ; stored program tag is 1..24
        mov dl, al
        xor bx, bx
.loop:
        cmp byte [cs:mute_voice_program+bx], dl
        jne .keep
        mov byte [cs:mute_voice_program+bx], 0
        mov byte [cs:mute_voice_pad+bx], 0
.keep:
        inc bx
        cmp bx, MUTE_VOICE_COUNT
        jb .loop
.return:
        ret

; A zero program tag is invalid.  Nonzero values encode program+1, and the
; parallel byte records the canonical pad.  Group membership stays live in
; the storage table and is deliberately not copied into these voice tags.
; mute_context_* is a write-only mirror of the context resolved by the most
; recent allocation, kept for read-only emulator observers.
mute_context_valid:   db 0
mute_context_program: db 0
mute_context_pad:     db 0
mute_context_group:   db 0
mute_voice_program:   times MUTE_VOICE_COUNT db 0
mute_voice_pad:       times MUTE_VOICE_COUNT db 0
