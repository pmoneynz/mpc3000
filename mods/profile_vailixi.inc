; Generic Vailixi 3.50 profile: the interleaved LS/MS pair under
; 07-rom/Vailixi 3.50/ (mods/build_mod_sys.py @mods/WAVE.args).  Selected by
; mods/profile.inc when no other profile is defined.  The image carries no
; relocation table, so RELOC_PREV marks nothing.  DGROUP objects are offsets
; in DGROUP_SEG; T_SSSS_OOOO is the far target SSSS:OOOO.

%macro RELOC_PREV 0
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

SND_SEG    equ 0xA2AE           ; sound records at A2AE:4800 + idx*24h
DGROUP_SEG equ 0x8010           ; DGROUP, DS in the hooked routines
CAVE_SEG   equ 0xF07D           ; this cave, file 0x707D0 (build_mod_sys.py)
PLAYER_SEG equ 0xCFC6           ; stock sound player code

; ---------------------------------------------------------------- shared

SND_DIR    equ 0x4800           ; first sound record in SND_SEG
FB         equ 0x1591           ; 8010:1591, 30 bytes x 64 rows, bit 7 = left
KEY_REPEAT equ 0xD69A           ; normalized-key repeat count (D6E0:001B)
%define T_B1B1_004F 0xB1B1:0x004F       ; save the text shadow (INT 43 AX=5)
%define T_B1B1_0055 0xB1B1:0x0055       ; restore that shadow (INT 43 AX=6)
%define T_BDE3_000E 0xBDE3:0x000E       ; next key after the global filter
%define T_C4C8_0409 0xC4C8:0x0409       ; clear, text mode, INT 43 AX=1
%define T_C4C8_0F0D 0xC4C8:0x0F0D       ; blit FB
%define T_C4C8_0F5F 0xC4C8:0x0F5F       ; graphics mode + blit FB
%define T_B99A_1595 0xB99A:0x1595       ; leave Edit Sound for the menu
%define T_B99A_16BB 0xB99A:0x16BB       ; redraw the 17 Edit Sound fields

; ---------------------------------------------------------------- view (wave.asm)

BUF_W      equ 0x2400           ; Best st's read buffer A2AE:0000, words
BUSY       equ 0x9757           ; transfer busy counter (INC/DEC round CF92)
MODE       equ 0xD7CB           ; 'L' = Program/Sounds
OPTION     equ 0xD7CA           ; 6 = Edit Sound
ZONE_ST    equ 0xEDBB           ; zone start / end dwords (Edit Sound fields)
ZONE_EN    equ 0xEDB7
%define T_B060_0428 0xB060:0x0428       ; B060:035D key loop: stock Help
%define T_B060_0459 0xB060:0x0459       ; B060:035D key loop: other keys
%define T_B060_06E2 0xB060:0x06E2       ; B060:035D key loop: return key SI
%define T_B99A_0AF3 0xB99A:0x0AF3       ; Edit Sound Do dispatch (key 75h)
%define T_CF92_000C 0xCF92:0x000C       ; wave transfer (dst, wave, count, dir)

; ---------------------------------------------------------------- numeric entry (wave_numeric.inc)

NUM_EDITING equ 0x7D74          ; 0 while an entry buffer is active
%define T_B060_006B 0xB060:0x006B       ; select a live B99A field record
%define T_B060_021C 0xB060:0x021C       ; initialize its parser and display
%define T_B060_0715 0xB060:0x0715       ; commit the active entry buffer
%define T_B1B1_0008 0xB1B1:0x0008       ; cursor shape (0 hides)
%define T_B31B_0007 0xB31B:0x0007       ; numeric field editor (key, flags)
%define T_B99A_2619 0xB99A:0x2619       ; component triple (far) -> frames
%define T_B99A_266D 0xB99A:0x266D       ; frames -> component triple (far)

; ---------------------------------------------------------------- audition (wave_playback.inc)

PLAYER_CE9_RET equ 0x0D70       ; CFC6:0D70, CE9's return from CFC6:039E
%define T_CFC6_0CE9 0xCFC6:0x0CE9       ; start the Sound at index (word)
%define T_CFC6_0D75 0xCFC6:0x0D75       ; any voice pending (AX=1), else 0
%define T_CFC6_0D93 0xCFC6:0x0D93       ; stop all 32 channels (Ply/Stp stop)
%define T_CFC6_06A3 0xCFC6:0x06A3       ; 039E after the 30 ms SUB/SBB at 069D
%define T_CFC6_089E 0xCFC6:0x089E       ; 039E after the tick MOV/CMP at 0897
%define T_CFC6_0B21 0xCFC6:0x0B21       ; 039E epilogue: no voice started

; ---------------------------------------------------------------- zones (wave_zones.inc)

KEY_QUEUE  equ 0x12BC           ; FB00 key queue: +0 capacity, +2 count
LIST_SELECTION equ 0xE40A       ; sorted Sound list position, word
%define T_FB00_06B9 0xFB00:0x06B9       ; key queue unget: insert at read head
%define T_B99A_0009 0xB99A:0x0009       ; Edit Sound after its replaced prologue
%define T_B99A_006B 0xB99A:0x006B       ; Edit Sound after the sorted-list seam
%define T_B99A_04E3 0xB99A:0x04E3       ; field 0 handler, sound present
%define T_B99A_082E 0xB99A:0x082E       ; Edit Sound input loop

; ---------------------------------------------------------------- CHOP (wave_chop.inc)

CHOP_SEQ_STATE equ 0xA7AE       ; transport state (HYPOTHESIS); Do guard
CHOP_SAFE_LOCK equ 0x862F       ; EDIT SND <Do> safe lock setting
CHOP_MUTE_EDIT equ 0x8629       ; mute audio during EDIT SND setting
CHOP_DO        equ 0xEDB5       ; Do choice index
CHOP_DO_LABEL  equ 0x3781       ; Do field label string
%define CHOP_STOCK_OPTIONS 10       ; stock Do options COPY ZONE->TEMP .. REVERSE ZONE
%define CHOP_HAS_SAFE_LOCK             ; stock Do handlers refuse on [SEQ]&&[SAFE_LOCK]
%define CHOP_HAS_EDIT_MUTE             ; stock copy wrapper mutes while [MUTE_EDIT]
CHOP_OPT_0     equ 0x3632       ; stock Do option strings 0..9
CHOP_OPT_1     equ 0x3643
CHOP_OPT_2     equ 0x3654
CHOP_OPT_3     equ 0x3665
CHOP_OPT_4     equ 0x3676
CHOP_OPT_5     equ 0x3682
CHOP_OPT_6     equ 0x3693
CHOP_OPT_7     equ 0x36A4
CHOP_OPT_8     equ 0x36B5
CHOP_OPT_9     equ 0x36C2
%define T_B1B1_0026 0xB1B1:0x0026       ; cursor position (INT 43 AX=3)
%define T_B1B1_005B 0xB1B1:0x005B       ; put string (far) at the cursor
%define T_B354_01C6 0xB354:0x01C6       ; add a choice field record
%define T_B3C7_0007 0xB3C7:0x0007       ; stock error box (error number)
%define T_B99A_048F 0xB99A:0x048F       ; Edit Sound after the Do field
%define T_B99A_0B0D 0xB99A:0x0B0D       ; stock Do jump table (BX = 0..9)
%define T_B99A_27F2 0xB99A:0x27F2       ; rebuild the sorted Sound list
%define T_C6C2_173D 0xC6C2:0x173D       ; collision-free ZONEnnn name
%define T_D0C0_0236 0xD0C0:0x0236       ; free wave words, DX:AX
%define T_D0C0_0611 0xD0C0:0x0611       ; allocate Sound (name, length, stereo)
%define T_D0C0_084D 0xD0C0:0x084D       ; free record count
%define T_D0C0_086F 0xD0C0:0x086F       ; rebuild allocation state
%define T_D0C0_0B19 0xD0C0:0x0B19       ; free Sound (index, mode, flag)
%define T_D0C0_0B1F 0xD0C0:0x0B1F       ; free Sound after its replaced prologue
%define T_D0C0_0E50 0xD0C0:0x0E50       ; copy wave words (src, dest, count)
%define T_D980_000C 0xD980:0x000C       ; mute 1 / unmute 0 (port 6A)

; ---------------------------------------------------------------- mute storage (mute_storage.inc)

%define T_C887_19FB 0xC887:0x19FB       ; after the program-record copy
%define T_CEE6_0086 0xCEE6:0x0086       ; close (handle)
%define T_CF0C_0073 0xCF0C:0x0073       ; fixed-size read (buffer, handle, n)
%define T_CF0C_0096 0xCF0C:0x0096       ; fixed-size write (buffer, handle, n)
%define T_CF37_04B3 0xCF37:0x04B3       ; program init after its prologue

; ---------------------------------------------------------------- mute voice (mute_voice.inc)

MUTE_CURRENT_PROGRAM equ 0xE60E ; selected program 0..23
%define T_CF37_0002 0xCF37:0x0002       ; voice allocator
%define T_CFC6_0007 0xCFC6:0x0007       ; shared note-on engine (event far)
%define T_D1F7_0126 0xD1F7:0x0126       ; reserve AMX resource 1 (allocation lock)
%define T_D21F_0008 0xD21F:0x0008       ; one-channel stop (channel)
%define T_D9F2_003D 0xD9F2:0x003D       ; first pad slot mapped to a note
MUTE_PAD_MODE  equ 0x8375       ; non-zero: pad slot notes come from MUTE_PAD_NOTES (D9F2:000C)
MUTE_PAD_NOTES equ 0x8376       ; 64 pad slot notes used while MUTE_PAD_MODE is set

; ---------------------------------------------------------------- mute UI (mute_ui.inc)

MUTE_PROGRAM   equ 0xE60E       ; selected program 0..23
MUTE_RECORD    equ 0xE5F9       ; far pointer to its program record
MUTE_PAD       equ 0xD6AC       ; current pad slot (pad + bank)
MUTE_NOTE      equ 0xD6AD       ; note of the last pad event
MUTE_NOTE_MIDI equ 0xD6AE       ; note of the last MIDI event
%define T_C887_006B 0xC887:0x006B       ; stock menu dispatch continuation
%define T_C887_00F1 0xC887:0x00F1       ; menu return continuation (DL)
%define T_CA45_0008 0xCA45:0x0008       ; select program (index)
%define T_D9F2_000C 0xD9F2:0x000C       ; effective pad slot -> note

%macro PUSH_CAVE_SEG 0
        push strict word CAVE_SEG
        RELOC_PREV
%endmacro
