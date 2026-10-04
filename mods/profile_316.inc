; OS 3.16 profile: SKELETON.  Selected by mods/profile.inc with -DPROFILE_316.
; Nothing here is mapped yet.  Every symbol expands to an undefined
; UNMAPPED_<name>, so each use fails with "symbol `UNMAPPED_<name>' not
; defined" until the 3.16 mapping work supplies its value.  Each comment
; gives the generic Vailixi 3.50 address and what the routine or object is.
;
; Every segment word in the 3.16 cave carries an MZ relocation.  RELOC_PREV
; defines the global label __reloc_<n> at the segment word just emitted; the
; builder collects every __reloc_* symbol from the NASM map.

%assign RELOC_N 0

%macro RELOC_PREV 0
%assign RELOC_N RELOC_N+1
__reloc_%[RELOC_N] equ $-2
%endmacro

%macro FCALL 1
        call %1
        RELOC_PREV
%endmacro

%macro FJMP 1
        jmp %1
        RELOC_PREV
%endmacro

; ---------------------------------------------------------------- segments

%define SND_SEG UNMAPPED_SND_SEG       ; A2AE sound segment: read buffer at 0000, records at 4800
%define DGROUP_SEG UNMAPPED_DGROUP_SEG ; 8010 DGROUP, DS in the hooked routines
%define CAVE_SEG UNMAPPED_CAVE_SEG     ; F07D this cave (generic file 0x707D0)
%define PLAYER_SEG UNMAPPED_PLAYER_SEG ; CFC6 stock sound player code

; ---------------------------------------------------------------- shared

%define SND_DIR UNMAPPED_SND_DIR         ; A2AE:4800 first sound record, 24h bytes each
%define FB UNMAPPED_FB                   ; 8010:1591 LCD framebuffer, 30 bytes x 64 rows, bit 7 = left
%define KEY_REPEAT UNMAPPED_KEY_REPEAT   ; 8010:D69A normalized-key repeat count (D6E0:001B)
%define T_B1B1_004F UNMAPPED_T_B1B1_004F ; B1B1:004F save the text shadow (INT 43 AX=5)
%define T_B1B1_0055 UNMAPPED_T_B1B1_0055 ; B1B1:0055 restore that shadow (INT 43 AX=6)
%define T_BDE3_000E UNMAPPED_T_BDE3_000E ; BDE3:000E next key after the global filter
%define T_C4C8_0409 UNMAPPED_T_C4C8_0409 ; C4C8:0409 clear, text mode, INT 43 AX=1
%define T_C4C8_0F0D UNMAPPED_T_C4C8_0F0D ; C4C8:0F0D blit FB
%define T_C4C8_0F5F UNMAPPED_T_C4C8_0F5F ; C4C8:0F5F graphics mode + blit FB
%define T_B99A_1595 UNMAPPED_T_B99A_1595 ; B99A:1595 leave Edit Sound for the menu
%define T_B99A_16BB UNMAPPED_T_B99A_16BB ; B99A:16BB redraw the 17 Edit Sound fields

; ---------------------------------------------------------------- view (wave.asm)

%define BUF_W UNMAPPED_BUF_W             ; 2400h words: Best st's read buffer A2AE:0000..47FF
%define BUSY UNMAPPED_BUSY               ; 8010:9757 transfer busy counter (INC/DEC round CF92)
%define MODE UNMAPPED_MODE               ; 8010:D7CB mode, 'L' = Program/Sounds
%define OPTION UNMAPPED_OPTION           ; 8010:D7CA option, 6 = Edit Sound
%define ZONE_ST UNMAPPED_ZONE_ST         ; 8010:EDBB zone start dword (Edit Sound field)
%define ZONE_EN UNMAPPED_ZONE_EN         ; 8010:EDB7 zone end dword (Edit Sound field)
%define T_B060_0428 UNMAPPED_T_B060_0428 ; B060:0428 B060:035D key loop: stock Help
%define T_B060_0459 UNMAPPED_T_B060_0459 ; B060:0459 B060:035D key loop: other keys
%define T_B060_06E2 UNMAPPED_T_B060_06E2 ; B060:06E2 B060:035D key loop: return key SI
%define T_B99A_0AF3 UNMAPPED_T_B99A_0AF3 ; B99A:0AF3 Edit Sound Do dispatch (key 75h)
%define T_CF92_000C UNMAPPED_T_CF92_000C ; CF92:000C wave transfer (dst, wave, count, dir)

; ---------------------------------------------------------------- numeric entry (wave_numeric.inc)

%define NUM_EDITING UNMAPPED_NUM_EDITING ; 8010:7D74 0 while an entry buffer is active
%define T_B060_006B UNMAPPED_T_B060_006B ; B060:006B select a live B99A field record
%define T_B060_021C UNMAPPED_T_B060_021C ; B060:021C initialize its parser and display
%define T_B060_0715 UNMAPPED_T_B060_0715 ; B060:0715 commit the active entry buffer
%define T_B1B1_0008 UNMAPPED_T_B1B1_0008 ; B1B1:0008 cursor shape (0 hides)
%define T_B31B_0007 UNMAPPED_T_B31B_0007 ; B31B:0007 numeric field editor (key, flags)
%define T_B99A_2619 UNMAPPED_T_B99A_2619 ; B99A:2619 component triple (far) -> frames
%define T_B99A_266D UNMAPPED_T_B99A_266D ; B99A:266D frames -> component triple (far)

; ---------------------------------------------------------------- audition (wave_playback.inc)

%define PLAYER_CE9_RET UNMAPPED_PLAYER_CE9_RET ; CFC6:0D70 offset, CE9's return from CFC6:039E
%define T_CFC6_0CE9 UNMAPPED_T_CFC6_0CE9       ; CFC6:0CE9 start the Sound at index (word)
%define T_CFC6_0D75 UNMAPPED_T_CFC6_0D75       ; CFC6:0D75 first active voice slot, 0 if none
%define T_CFC6_0D93 UNMAPPED_T_CFC6_0D93       ; CFC6:0D93 stop all 32 channels (Ply/Stp stop)
%define T_CFC6_06A3 UNMAPPED_T_CFC6_06A3       ; CFC6:06A3 039E after the 30 ms SUB/SBB at 069D
%define T_CFC6_089E UNMAPPED_T_CFC6_089E       ; CFC6:089E 039E after the tick MOV/CMP at 0897
%define T_CFC6_0B21 UNMAPPED_T_CFC6_0B21       ; CFC6:0B21 039E epilogue: no voice started

; ---------------------------------------------------------------- zones (wave_zones.inc)

%define KEY_QUEUE UNMAPPED_KEY_QUEUE           ; 8010:12BC FB00 key queue: +0 capacity, +2 count
%define LIST_SELECTION UNMAPPED_LIST_SELECTION ; 8010:E40A sorted Sound list position, word
%define T_FB00_06B9 UNMAPPED_T_FB00_06B9       ; FB00:06B9 key queue unget: insert at read head
%define T_B99A_0009 UNMAPPED_T_B99A_0009       ; B99A:0009 Edit Sound after its replaced prologue
%define T_B99A_006B UNMAPPED_T_B99A_006B       ; B99A:006B Edit Sound after the sorted-list seam
%define T_B99A_04E3 UNMAPPED_T_B99A_04E3       ; B99A:04E3 field 0 handler, sound present
%define T_B99A_082E UNMAPPED_T_B99A_082E       ; B99A:082E Edit Sound input loop

; ---------------------------------------------------------------- CHOP (wave_chop.inc)

%define CHOP_SEQ_STATE UNMAPPED_CHOP_SEQ_STATE ; 8010:A7AE transport state (HYPOTHESIS); Do guard
%define CHOP_SAFE_LOCK UNMAPPED_CHOP_SAFE_LOCK ; 8010:862F EDIT SND <Do> safe lock setting
%define CHOP_MUTE_EDIT UNMAPPED_CHOP_MUTE_EDIT ; 8010:8629 mute audio during EDIT SND setting
%define CHOP_DO UNMAPPED_CHOP_DO               ; 8010:EDB5 Do choice index
%define CHOP_DO_LABEL UNMAPPED_CHOP_DO_LABEL   ; 8010:3781 Do field label string
%define CHOP_OPT_0 UNMAPPED_CHOP_OPT_0         ; 8010:3632 stock Do option string 0
%define CHOP_OPT_1 UNMAPPED_CHOP_OPT_1         ; 8010:3643 stock Do option string 1
%define CHOP_OPT_2 UNMAPPED_CHOP_OPT_2         ; 8010:3654 stock Do option string 2
%define CHOP_OPT_3 UNMAPPED_CHOP_OPT_3         ; 8010:3665 stock Do option string 3
%define CHOP_OPT_4 UNMAPPED_CHOP_OPT_4         ; 8010:3676 stock Do option string 4
%define CHOP_OPT_5 UNMAPPED_CHOP_OPT_5         ; 8010:3682 stock Do option string 5
%define CHOP_OPT_6 UNMAPPED_CHOP_OPT_6         ; 8010:3693 stock Do option string 6
%define CHOP_OPT_7 UNMAPPED_CHOP_OPT_7         ; 8010:36A4 stock Do option string 7
%define CHOP_OPT_8 UNMAPPED_CHOP_OPT_8         ; 8010:36B5 stock Do option string 8
%define CHOP_OPT_9 UNMAPPED_CHOP_OPT_9         ; 8010:36C2 stock Do option string 9
%define T_B1B1_0026 UNMAPPED_T_B1B1_0026       ; B1B1:0026 cursor position (INT 43 AX=3)
%define T_B1B1_005B UNMAPPED_T_B1B1_005B       ; B1B1:005B put string (far) at the cursor
%define T_B354_01C6 UNMAPPED_T_B354_01C6       ; B354:01C6 add a choice field record
%define T_B3C7_0007 UNMAPPED_T_B3C7_0007       ; B3C7:0007 stock error box (error number)
%define T_B99A_048F UNMAPPED_T_B99A_048F       ; B99A:048F Edit Sound after the Do field
%define T_B99A_0B0D UNMAPPED_T_B99A_0B0D       ; B99A:0B0D stock Do jump table (BX = 0..9)
%define T_B99A_27F2 UNMAPPED_T_B99A_27F2       ; B99A:27F2 rebuild the sorted Sound list
%define T_C6C2_173D UNMAPPED_T_C6C2_173D       ; C6C2:173D collision-free ZONEnnn name
%define T_D0C0_0236 UNMAPPED_T_D0C0_0236       ; D0C0:0236 free wave words, DX:AX
%define T_D0C0_0611 UNMAPPED_T_D0C0_0611       ; D0C0:0611 allocate Sound (name, length, stereo)
%define T_D0C0_084D UNMAPPED_T_D0C0_084D       ; D0C0:084D free record count
%define T_D0C0_086F UNMAPPED_T_D0C0_086F       ; D0C0:086F rebuild allocation state
%define T_D0C0_0B19 UNMAPPED_T_D0C0_0B19       ; D0C0:0B19 free Sound (index, mode, flag)
%define T_D0C0_0B1F UNMAPPED_T_D0C0_0B1F       ; D0C0:0B1F free Sound after its replaced prologue
%define T_D0C0_0E50 UNMAPPED_T_D0C0_0E50       ; D0C0:0E50 copy wave words (src, dest, count)
%define T_D980_000C UNMAPPED_T_D980_000C       ; D980:000C mute 1 / unmute 0 (port 6A)

; ---------------------------------------------------------------- mute storage (mute_storage.inc)

%define T_C887_19FB UNMAPPED_T_C887_19FB ; C887:19FB after the program-record copy
%define T_CEE6_0086 UNMAPPED_T_CEE6_0086 ; CEE6:0086 close (handle)
%define T_CF0C_0073 UNMAPPED_T_CF0C_0073 ; CF0C:0073 fixed-size read (buffer, handle, n)
%define T_CF0C_0096 UNMAPPED_T_CF0C_0096 ; CF0C:0096 fixed-size write (buffer, handle, n)
%define T_CF37_04B3 UNMAPPED_T_CF37_04B3 ; CF37:04B3 program init after its prologue

; ---------------------------------------------------------------- mute voice (mute_voice.inc)

%define MUTE_CURRENT_PROGRAM UNMAPPED_MUTE_CURRENT_PROGRAM ; 8010:E60E selected program 0..23
%define T_CF37_0002 UNMAPPED_T_CF37_0002                   ; CF37:0002 voice allocator
%define T_CFC6_0007 UNMAPPED_T_CFC6_0007                   ; CFC6:0007 shared note-on engine (event far)
%define T_D21F_0008 UNMAPPED_T_D21F_0008                   ; D21F:0008 one-channel stop (channel)
%define T_D9F2_003D UNMAPPED_T_D9F2_003D                   ; D9F2:003D first pad slot mapped to a note

; ---------------------------------------------------------------- mute UI (mute_ui.inc)

%define MUTE_PROGRAM UNMAPPED_MUTE_PROGRAM     ; 8010:E60E selected program 0..23
%define MUTE_RECORD UNMAPPED_MUTE_RECORD       ; 8010:E5F9 far pointer to its program record
%define MUTE_PAD UNMAPPED_MUTE_PAD             ; 8010:D6AC current pad slot (pad + bank)
%define MUTE_NOTE UNMAPPED_MUTE_NOTE           ; 8010:D6AD note of the last pad event
%define MUTE_NOTE_MIDI UNMAPPED_MUTE_NOTE_MIDI ; 8010:D6AE note of the last MIDI event
%define T_C887_006B UNMAPPED_T_C887_006B       ; C887:006B stock menu dispatch continuation
%define T_C887_00F1 UNMAPPED_T_C887_00F1       ; C887:00F1 menu return continuation (DL)
%define T_CA45_0008 UNMAPPED_T_CA45_0008       ; CA45:0008 select program (index)
%define T_D9F2_000C UNMAPPED_T_D9F2_000C       ; D9F2:000C effective pad slot -> note
