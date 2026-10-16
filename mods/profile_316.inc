; OS 3.16 profile (M3K316.SYS).  Selected by mods/profile.inc with -DPROFILE_316.
; Addresses are relative to the 3.16 load image: seg:off as stored in the
; file, image offset = seg*16+off; the EPROM loader adds the load segment L
; (6900h on 3.12/3.50, 7000h on 3.08/3.11) to every relocated segment word.
; DS offsets are 3.16 DGROUP (relative segment 609Ch).  Each comment gives the
; generic Vailixi 3.50 address the symbol is named after, then what it is.
; Evidence: notes/port_316.md (orchestrator cross-checks of seven mapping
; packages, 2026-10-05).
;
; Every segment word in the 3.16 cave carries an MZ relocation.  RELOC_PREV
; defines the global label __reloc_<n> at the segment word just emitted; the
; builder (mods/build_wave316.py) collects every __reloc_* symbol.

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

CAVE_HOME  equ 0x7E00           ; cave home paragraph, above 3.16's extent 7DFBh
SND_SEG    equ 0x539D           ; A2AE: sound segment (buffer 0000, records 4800)
DGROUP_SEG equ 0x609C           ; 8010: DGROUP, DS in the hooked routines
CAVE_SEG   equ CAVE_HOME        ; F07D: this cave at its home
PLAYER_SEG equ 0x20ED           ; CFC6: stock sound player module

; ---------------------------------------------------------------- shared

SND_DIR    equ 0x4800           ; first sound record in SND_SEG, 24h bytes each
FB         equ 0x1579           ; 1591: LCD framebuffer, 30 bytes x 64 rows
KEY_REPEAT equ 0xD387           ; D69A: normalized-key repeat count (2D0B:001D)
%define T_B1B1_004F 0x0427:0x0059       ; save the text shadow (INT 43 AX=5)
%define T_B1B1_0055 0x0427:0x005F       ; restore that shadow (INT 43 AX=6)
%define T_BDE3_000E 0x0F6B:0x0009       ; next key after the global filter
%define T_C4C8_0409 0x1650:0x03FD       ; clear, text mode, INT 43 AX=1
%define T_C4C8_0F0D 0x1650:0x0F01       ; blit FB
%define T_C4C8_0F5F 0x1650:0x0F53       ; graphics mode + blit FB
%define T_B99A_1595 0x0B72:0x1209       ; leave Edit Sound for the menu
%define T_B99A_16BB 0x0B72:0x132B       ; redraw the 17 Edit Sound fields

; ---------------------------------------------------------------- view (wave.asm)

BUF_W      equ 0x2400           ; Best st's read buffer SND_SEG:0000, words
BUSY       equ 0x9444           ; 9757: transfer busy counter (stock 3.16 Edit
                                ; Sound does not wrap its reads; kept, harmless)
MODE       equ 0xD4B8           ; D7CB: mode, 'L' = Program/Sounds
OPTION     equ 0xD4B7           ; D7CA: option, 6 = Edit Sound
ZONE_ST    equ 0xE45A           ; EDBB: zone start dword (Edit Sound field)
ZONE_EN    equ 0xE456           ; EDB7: zone end dword
%define T_B060_0428 0x02D7:0x0422       ; field editor key loop: stock Help
%define T_B060_0459 0x02D7:0x0453       ; field editor key loop: other keys
%define T_B060_06E2 0x02D7:0x06DC       ; field editor key loop: return key SI
%define T_B99A_0AF3 0x0B72:0x0AF8       ; Edit Sound Do dispatch (key 75h)
%define T_CF92_000C 0x20BA:0x0002       ; wave transfer (dst, wave, count, dir)

; ---------------------------------------------------------------- numeric entry (wave_numeric.inc)

NUM_EDITING equ 0x7A62          ; 7D74: 0 while an entry buffer is active
%define T_B060_006B 0x02D7:0x0065       ; select a live Edit Sound field record
%define T_B060_021C 0x02D7:0x0216       ; initialize its parser and display
%define T_B060_0715 0x02D7:0x070F       ; commit the active entry buffer
%define T_B1B1_0008 0x0427:0x0012       ; cursor shape (0 hides)
%define T_B31B_0007 0x058F:0x000B       ; numeric field editor (key, flags)
%define T_B99A_2619 0x0B72:0x2124       ; component triple (far) -> frames
%define T_B99A_266D 0x0B72:0x2178       ; frames -> component triple (far)

; ---------------------------------------------------------------- audition (wave_playback.inc)

PLAYER_CE9_RET equ 0x0D76               ; 0D70: CEF's return from the player 03A4
%define T_CFC6_0CE9 0x20ED:0x0CEF       ; start the Sound at index (word)
%define T_CFC6_0D75 0x20ED:0x0D7B       ; any voice pending (AX=1), else 0
%define T_CFC6_0D93 0x20ED:0x0D99       ; stop all 32 channels (Ply/Stp stop)
%define T_CFC6_06A3 0x20ED:0x06A9       ; player after the 30 ms SUB/SBB at 06A3
%define T_CFC6_089E 0x20ED:0x08A4       ; player after the tick MOV/CMP at 089D
%define T_CFC6_0B21 0x20ED:0x0B27       ; player epilogue: no voice started

; ---------------------------------------------------------------- zones (wave_zones.inc)

KEY_QUEUE  equ 0x12A4           ; 12BC: AMX key queue, byte queue of 8
LIST_SELECTION equ 0xE0F7       ; E40A: sorted Sound list position, word
%define T_FB00_06B9 0x47BF:0x06B3       ; AMX queue push-front (3.16's own AMX)
%define T_B99A_0009 0x0B72:0x0013       ; Edit Sound after its replaced prologue
%define T_B99A_006B 0x0B72:0x0070       ; Edit Sound after the sorted-list seam
%define T_B99A_04E3 0x0B72:0x04E8       ; field 0 handler, sound present
%define T_B99A_082E 0x0B72:0x0833       ; Edit Sound input loop

; ---------------------------------------------------------------- CHOP (wave_chop.inc)

; 3.16 has 8 stock Do options (handlers 0B72:[1244]); the cave adds Vailixi's
; COPY ZONE-> SND and TRUNC SFT ST+END in Vailixi's list order (CHOP_EDITDO),
; under PMONEY's names ZONE->NEW SOUND and CROP SOFT ST-END.
; Stock 3.16 has no "safe lock" and no Edit Sound mute; PMONEY adds both as
; Extra Settings (xparams316.inc), stored inverted (0 = ON), with the lock
; checked for the stock handlers too (CHOP_LOCK_STOCK).  It has no ZONE%03d naming
; (CHOP_OWN_NAMES), and no allocation rebuild at Edit Sound entry
; (CHOP_REBUILD_FIRST).
CHOP_SEQ_STATE equ 0xA49B       ; A7AE: transport state (HYPOTHESIS)
CHOP_SAFE_LOCK equ 0x831D       ; 862F: Extra Settings "Lock Edit Sound <Do>" (inverted)
CHOP_MUTE_EDIT equ 0x8317       ; 8629: Extra Settings "Mute outputs during sound edits" (inverted)
%define CHOP_HAS_SAFE_LOCK
%define CHOP_HAS_EDIT_MUTE
%define CHOP_SETTINGS_INVERTED
%define CHOP_LOCK_STOCK
CHOP_DO        equ 0xE454       ; EDB5: Do choice index
CHOP_DO_LABEL  equ 0x33F3       ; 3781: "Do:"
%define CHOP_STOCK_OPTIONS 10       ; Do list before CHOP ZONE, in Vailixi 3.50 order
%define CHOP_EDITDO                 ; COPY ZONE-> SND and TRUNC SFT ST+END run in the cave
%define CHOP_CAVE_OPTS 0x0082       ; list entries 1 and 7 are cave strings (segment CAVE_SEG)
CHOP_OPT_0     equ 0x32C6       ; COPY ZONE-> TEMP      3.16 stock 0
CHOP_OPT_1     equ editdo_copy_text  ; ZONE->NEW SOUND  cave (Vailixi COPY ZONE-> SND, DS 3643)
CHOP_OPT_2     equ 0x32D7       ; INS TMP-> ZON ST      3.16 stock 1
CHOP_OPT_3     equ 0x32E8       ; INS TMP-> ZN END      3.16 stock 2
CHOP_OPT_4     equ 0x32F9       ; DELETE ZONE           3.16 stock 3
CHOP_OPT_5     equ 0x3305       ; DEL BEFR SOFT ST      3.16 stock 4
CHOP_OPT_6     equ 0x3316       ; DEL AFTR SFT END      3.16 stock 5
CHOP_OPT_7     equ editdo_trunc_text ; CROP SOFT ST-END cave (Vailixi TRUNC SFT ST+END, DS 36A4)
CHOP_OPT_8     equ 0x3327       ; SILENCE ZONE          3.16 stock 6
CHOP_OPT_9     equ 0x3334       ; REVERSE ZONE          3.16 stock 7
EDITDO_TEMP_NAME equ 0x3446     ; 37D4: "TEMPORARY999"
EDITDO_SOFTKEYS  equ 0x3420     ; 37AE: "<Ply/Stp> <Best st>  <Play X>    <Do>"
%define T_B99A_22C4 0x0B72:0x1DF1       ; delete frames [from,to) of a Sound (index, from, to)
%define T_B99A_0FA9 0x0B72:0x0DFF       ; DEL BEFR SOFT ST handler (Vailixi: after its safe lock)
%define CHOP_OWN_NAMES
%define CHOP_REBUILD_FIRST
%define T_B1B1_0026 0x0427:0x0030       ; cursor position (INT 43 AX=3)
%define T_B1B1_005B 0x0427:0x0065       ; put string (far) at the cursor
%define T_B354_01C6 0x05C8:0x01CA       ; add a choice field record
%define T_B3C7_0007 0x063B:0x000B       ; stock error box (error number)
%define T_B99A_048F 0x0B72:0x0494       ; Edit Sound after the Do field
%define T_B99A_0B0D 0x0B72:0x0B12       ; stock Do jump table (BX = 0..7)
%define T_B99A_27F2 0x0B72:0x22FD       ; rebuild the sorted Sound list
%define T_D0C0_0236 0x21E7:0x023C       ; free wave words, DX:AX
%define T_D0C0_0611 0x21E7:0x0617       ; allocate Sound (name, length, stereo)
%define T_D0C0_084D 0x21E7:0x0853       ; free record count
%define T_D0C0_086F 0x21E7:0x0875       ; rebuild allocation state
%define T_D0C0_0B19 0x21E7:0x0B1F       ; free Sound (index, mode, flag)
%define T_D0C0_0B1F 0x21E7:0x0B25       ; free Sound after its replaced prologue
%define T_D0C0_0D17 0x21E7:0x0D1D       ; find Sound by name: index, or -4
%define T_D0C0_0E50 0x21E7:0x0E56       ; copy wave words (src, dest, count)

; ---------------------------------------------------------------- mute storage (mute_storage.inc)

%define T_C887_19FB 0x19F9:0x1A06       ; after the program-record copy
%define T_CEE6_0086 0x200D:0x008C       ; close (handle)
%define T_CF0C_0073 0x2033:0x0079       ; fixed-size read (buffer, handle, n)
%define T_CF0C_0096 0x2033:0x009C       ; fixed-size write (buffer, handle, n)
%define T_CF37_04B3 0x207C:0x02D9       ; program init after its prologue

; ---------------------------------------------------------------- mute voice (mute_voice.inc)

MUTE_CURRENT_PROGRAM equ 0xE2FB ; E60E: selected program 0..23
%define T_CF37_0002 0x205E:0x0008       ; voice allocator
%define T_CFC6_0007 0x20ED:0x000D       ; shared note-on engine (event far)
%define T_D1F7_0126 0x2325:0x011E       ; reserve AMX resource 1 (allocation lock)
%define T_D21F_0008 0x234D:0x0000       ; one-channel stop (channel)
%define T_D9F2_003D 0x301D:0x003B       ; first pad slot mapped to a note
MUTE_PAD_MODE  equ 0x8063       ; 8375: non-zero: pad slot notes come from MUTE_PAD_NOTES (301D:000A)
MUTE_PAD_NOTES equ 0x8064       ; 8376: 64 pad slot notes used while MUTE_PAD_MODE is set
%define T_F800_20FA 0x0009:0x20F6       ; signed 32-bit divide: 3.16's linked copy of the BIOS runtime (image 0x2186)
%define T_F800_2101 0x0009:0x20FD       ; unsigned 32-bit divide (same copy)
FIELD_INDEX    equ 0x7A67       ; 7D79: field committed by T_B060_035D (byte)
%define T_B1B1_0002 0x0427:0x000C       ; clear the text screen (INT 43 AX=1)
%define T_B509_2289 0x077D:0x1A35       ; new page: field list reset, clear, "== title ==" (far)
%define T_B354_03B1 0x05C8:0x03B5       ; add a numeric field (label, ptr, width, min, max, flags)
%define T_B99A_16DF 0x0B72:0x134F       ; "(ST)" or blanks for a Sound (index, row, col)
%define T_B77C_20C5 0x0955:0x20BF       ; '=' rule on row 6, cursor (7,0)
%define T_B060_0AD9 0x02D7:0x0AD3       ; redraw field n
%define T_B060_035D 0x02D7:0x0357       ; field editor key loop (flags) -> 0 on commit, else the key
%define T_B1FF_000C 0x0476:0x0006       ; spaces from the cursor to column n
%define T_B1BC_01EE 0x0432:0x01F8       ; printf at the cursor (far format, varargs)
%define T_E21A_000B 0x383B:0x0007       ; free sequence memory, bytes (DX:AX)
%define T_D6A0_0213 0x2CCC:0x0205       ; I-0055 probe (port 50h): AX = 1 present, 0 absent

; ---------------------------------------------------------------- mute UI (mute_ui.inc)

MUTE_PROGRAM   equ 0xE2FB       ; E60E: selected program 0..23
MUTE_RECORD    equ 0xE2E6       ; E5F9: far pointer to its program record
MUTE_PAD       equ 0xD399       ; D6AC: current pad slot (pad + bank)
MUTE_NOTE      equ 0xD39A       ; D6AD: note of the last pad event
MUTE_NOTE_MIDI equ 0xD39B       ; D6AE: note of the last MIDI event
%define T_C887_006B 0x19F9:0x0071       ; stock menu dispatch continuation
%define T_C887_00F1 0x19F9:0x00FC       ; menu return continuation (DL)
%define T_CA45_0008 0x19F9:0x1BF3       ; select program (index)
%define T_D9F2_000C 0x301D:0x000A       ; effective pad slot -> note

; ---------------------------------------------------------------- start-up (entry316.inc)

POOL_INIT_IMM equ 0x48535       ; image offset of 3.16's MOV BX,6FFFh pool end

; ---------------------------------------------------------------- Extra Settings (xparams316.inc)

; Settings in the zeroed reserve at the end of the parameter block (7C61,
; 6C2h bytes; Vailixi's block is one byte longer, so its offsets are +312h).
; Stored = shown XOR Vailixi default; 831B/831C are F12/F13 (scsi316.inc), 831E sync out.
XP_SND_STOP    equ 0x8316       ; 8628: stop sounds on STOP (default OFF, direct)
XP_MUTE_EDIT   equ 0x8317       ; 8629: mute during sound edits (default ON, inverted)
XP_WARN        equ 0x8318       ; 862A: transport warnings (default ON, inverted)
XP_STAY_EDIT   equ 0x8319       ; 862B: stay in Edit Sound on PLAY (default OFF)
XP_STAY_MIXER  equ 0x831A       ; 862C: stay in Mixer on PLAY (default OFF)
XP_SAFE_LOCK   equ 0x831D       ; 862F: Edit Sound Do lock (default ON, inverted)
XP_OFF_ON      equ 0x0030       ; 0020: far pointers "OFF", "ON ", NULL
XP_STR_OFF     equ 0x06BE       ; 0698: "OFF"
XP_STR_ON      equ 0x06C2       ; 069C: "ON "
XP_PLAY_SCREEN equ 0xD39C       ; D6AF: mode returned on PLAY / <Do it>
XP_SEQ_STATE   equ 0x8EF5       ; 9208: current-sequence byte (0 = record ready, HYPOTHESIS)
XP_POST_STOP   equ 0xA44F       ; A762: post-stop work done
%define T_E704_0007 0x3D25:0x0003       ; stop the transport and wait
%define T_C84C_016D 0x19D0:0x0165       ; Other page: cmp bx,5 / soft-key table
%define T_C84C_01DB 0x19D0:0x01CE       ; Other page: or dx,dx / return or key loop
%define T_DE5C_087D 0x3481:0x0839       ; key filter: return [bp+6]
%define T_DE5C_02F0 0x3481:0x02C2       ; key filter 'Q': jnz after cmp mode,'S'
%define T_DE5C_05BE 0x3481:0x057A       ; key filter STOP: after the post-stop work
%define T_C303_0386 0x148A:0x037E       ; Main: warning box and sequence switch
%define T_C303_03B4 0x148A:0x03AC       ; Main: Seq field reverts
%define T_B99A_175E 0x0B72:0x13A8       ; copy wrapper: add sp,4 after the TEMP lookup
%define T_B99A_17A7 0x0B72:0x1409       ; copy wrapper: allocation succeeded
%define T_B99A_1A05 0x0B72:0x15B0       ; insert: after cursor (7,0) and add sp,4
%define T_B99A_1E5C 0x0B72:0x19E5       ; reverse: same
%define T_B99A_215E 0x0B72:0x1CA5       ; silence: same
%define T_B99A_2301 0x0B72:0x1E1D       ; delete: same
%define T_B99A_2081 0x0B72:0x1BD9       ; reverse epilogue
%define T_B99A_22C0 0x0B72:0x1DED       ; silence epilogue
%define T_B99A_2615 0x0B72:0x2120       ; delete epilogue

; ---------------------------------------------------------------- Timing Correct (tc316.inc)

TC_NOTE      equ 0x7EBD         ; 81CF: TC note value; here always the stock index 0..6 (param block +25Ch)
TC_NV_DIRTY  equ 0xD38E         ; D6A1: parameter-block NVRAM save request (task 2FDF:0097)
TC_HELD      equ 0xA4A2         ; A7B5: TIMING CORRECT held, note repeat armed (2B6D:035A)
TC_PTRS      equ 0x6782         ; 6D02: 13 label far pointers + NULL (patched DGROUP)
TC_TICKS     equ 0x67BA         ; 6D3A: 13 intervals in ticks (patched DGROUP)
TC_PROJ      equ 0x67C7         ; new, patched DGROUP: extended index -> stock index
TC_CANON     equ 0x67D4         ; new, patched DGROUP: stock index -> extended index
TC_EXT       equ 0x67DB         ; new, patched DGROUP: extended (Vailixi) index 0..12, RAM only
%define TC_REPEAT_GATE
%define T_EC05_02B0 0x422F:0x02C0       ; playback tick after the repeat gate: CMP [95C8],0 (drum/MIDI repeat)
%define T_EC05_02C8 0x422F:0x02D8       ; playback tick: MOV AX,[86EE] (record-flush arm, repeat skipped)

; ---------------------------------------------------------------- Erase all (Disk 7, Vailixi B509:0BB3 / B766:0003)
%define T_B509_0C34 0x077D:0x0C38       ; Erase a File: stock <Erase it> arm
%define T_B509_21A1 0x077D:0x194D       ; raw file name -> NAME.EXT (src far, dst far)
%define T_CEE6_0175 0x200D:0x017B       ; find first (pattern far, 27-byte record far) -> 0 / <0
%define T_CEE6_01E1 0x200D:0x01E7       ; find next (same arguments)
%define T_CEE6_00C2 0x200D:0x00C8       ; delete file (raw name far) -> 0 / error
%define T_CF0C_0006 0x2033:0x000C       ; INT 41 service (fn, a, b, c)
%define T_D6E0_0000 0x2D0B:0x0002       ; wait for and take one key (AL)
%define T_D6E0_008B 0x2D0B:0x008D       ; drop queued soft keys
%define T_D6F3_000E 0x2D1F:0x0000       ; AX = keys queued
DISK_INDEX  equ 0x799D                  ; 7CAF: selected disk (0 = floppy)
DISK_LABELS equ 0x060C                  ; 05FC: disk label far pointers
S_DISK_FMT  equ 0x242A                  ; 2447: "Disk:%s"

; ---------------------------------------------------------------- Sync out (syncout316.inc)

SO_CLK_PORT  equ 0x7EAA         ; 81BC: Sync Out MIDI clock port, 0 OFF, 1-4 OUT A-D (block +249h)
SO_MTC_PORT  equ 0x8310         ; 8622: Sync Out MIDI time code port, same values (block +6AFh)
SO_ALL       equ 0x831E         ; 8630: block reserve; PMONEY bit 0 clock, bit 1 MTC on all four
SO_ERR       equ 0x9331         ; 9644: MIDI output suppressed while non-zero
SO_TXSH      equ 0x9315         ; 9628: TE7774 control shadows OUT A..D (bit 1 transmit interrupt)
SO_RTQ       equ 0x1244         ; 125C: real-time ring OUT A (16 bytes); B..D at +18h, +30h, +48h
SO_LBL_CLK   equ 0x6612         ; 6B92: "MIDI clock:"
SO_LBL_MTC   equ 0x663A         ; 6BBA: "MIDI tm code:"
SO_STR_OFF   equ 0x654B         ; 6AC7: "OFF"
SO_STR_OUT_A equ 0x654F         ; 6ACB: "OUT A"; "OUT B".."OUT D" at +6, +12, +18
SO_STR_ALL   equ 0x3287         ; 6AE3: 3.16's own "ALL" (choice list ALL/ZONE/TEMP/..., far ptr at DS:321E)
%define T_DC5B_0097 0x3286:0x008F       ; real-time sender after its entry test: DEC BX / JS ...
%define T_DA09_0000 0x3033:0x000E       ; queue CL in the DS:BX ring; keeps BX, CX, SI
%define T_DC5B_003B 0x3286:0x0039       ; buffer sender (buffer far, count, port word)

; ---------------------------------------------------------------- SCSI (scsi316.inc, Vailixi F12/F13)
%define T_D470_024F 0x2AB2:0x019C   ; sector I/O, multi-sector command (CMP [799A],5 ...)
%define T_D470_0249 0x2AB2:0x0196   ; sector I/O, stock one-block loop test (OR SI,SI / JNZ / JMP)
%define T_D470_02AF 0x2AB2:0x01FC   ; sector I/O epilogue: MOV AX,DX / POP DI / POP SI / LEAVE / RETF
%define T_D510_0006 0x2B36:0x000A   ; SCSI command with retries (id, cdb far, 6, buf far, bytes) -> AX
%define T_D3A7_0014 0x2A66:0x0012   ; SPC init: A2<-C0, check, A0<-07, AA<-00, A2<-08; AX 0/1
SCSI_CDB        equ 0x7984         ; 7C96: 6-byte CDB buffer (opcode, LBA 3, count, control)
SCSI_BLKSIZE    equ 0x7998         ; 7CAA: device block size from READ CAPACITY (200h / 800h)
SCSI_DEVTYPE    equ 0x799A         ; 7CAC: 0 = 512-byte blocks, 5 = 2048-byte blocks
SCSI_SYQUEST    equ 0xF16C         ; FACE: bit 0 = one block per command (INQUIRY "SyQuest SQ52")
SCSI_MULTI_OFF  equ 0x831B         ; 862D: multi-sector transfers, stored inverted (0 = ON, Vailixi default)
SCSI_UNIT       equ 0x830F         ; 8621: Make Active unit, 0 AUTO, 1-7 = ID 0-6
SCSI_AUTO_RESET equ 0x831C         ; 862E: reset the SPC after each failed ID probe (0 = OFF, Vailixi default)

; ---------------------------------------------------------------- Disk utilities (diskutil316.inc, Vailixi H6/F11/F14/F15)
; Port spec: notes/vailixi_features.md (F11, F14, F15, F16).  Each T_ below: first
; instruction shapes equal to the Vailixi routine (builder check).
%define T_B509_0FB3 0x077D:0x0F84   ; Copy/Format/Other: shl bx,1 / jmp [cs:bx+0FB1h], options 1-4
%define T_B509_13DE 0x077D:0x122E   ; Format Hard Disk: READ CAPACITY, stock partition-count page
%define T_B77C_20EA 0x0955:0x20E4   ; '=' rule row 6, cursor (7,0), "<Do it>"
%define T_EBC8_0003 0x41F3:0x0002   ; "Select option:" digit 1..max (byte far, max, flags) -> 0 / key
%define T_D470_02B5 0x2AB2:0x0202   ; READ(6) (unit, lba lo, lba hi, count, buffer far) -> 0 / code
%define T_D470_02D5 0x2AB2:0x0222   ; WRITE(6) (same)
%define T_D470_03AD 0x2AB2:0x02FA   ; READ CAPACITY (unit) -> DX:AX blocks (0: none); writes [SCSI_BLKSIZE]
%define T_D470_0458 0x2AB2:0x03A5   ; scan per [830F], mount, select partition A -> AX
%define T_D470_075E 0x2AB2:0x05A2   ; partition reader after push 61h/push 0D05h: Akai test
%define T_D510_008D 0x2B36:0x0091   ; SCSI code -> OS error number
%define T_F800_20C4 0x0009:0x20C0   ; DX:AX * CX:BX -> DX:AX (runtime copy)
SCSI_CHANGED    equ 0x799B         ; 7CAD: media changed, set by the partition writers (2A8A:0099 / D3CB:00A0)
SCSI_STATUS     equ 0x799E         ; 7CB0: last scan/mount result (byte; 077D:1113, 13F6)
DISK_LAYOUT     equ 0x79A4         ; 7CB6: 0 none, 1 MPC partitions, 2/3 Akai (byte; 2AB2:0548)
SCSI_ACTIVE     equ 0x79A6         ; 7CB8: active SCSI unit 0..6 (word; 2AB2:03D7)
PART_HEADS      equ 0x79A8         ; 7CBA: heads for INT 40 CHS->LBA (byte; 2A44:01DE)
PART_SPT        equ 0x79A9         ; 7CBB: sectors/track for the same (byte)
PART_COUNT      equ 0x79AA         ; 7CBC: volumes found, 0..26 (byte; 2AB2:070E clamps the disk index)
PART_TABLE      equ 0x79AF         ; 7CC1: 26 volume start LBAs (dwords, end 7A17 = 7D29)
S_FMT_TITLE     equ 0x289F         ; 28FA: Format page title "Format Hard Disk"
S_MENU_ITEM4    equ 0x2786         ; 27E9: "4.SCSI status, make SCSI device active\n"

; Code in the cave runs only at its home (every hook is {label} = label:CAVE_HOME,
; the builder rejects cave-to-cave far transfers), so CS = the relocated CAVE_SEG.
%macro PUSH_CAVE_SEG 0
        push cs
%endmacro
