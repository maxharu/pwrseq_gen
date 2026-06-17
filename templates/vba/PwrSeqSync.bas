Attribute VB_Name = "PwrSeqSync"
Option Explicit

Public Const PWRSEQ_DATA_START_ROW As Long = 4
Public Const PWRSEQ_MAX_ROW As Long = 500
Public Const PWRSEQ_COND_COL_NAME As Long = 1
Public Const PWRSEQ_COND_COL_TYPE As Long = 2
Public Const PWRSEQ_COND_COL_OPERATION As Long = 3
Public Const PWRSEQ_COND_COL_GROUP_INV As Long = 4
Public Const PWRSEQ_COND_COL_SIGNAL_START As Long = 5
Public Const PWRSEQ_COND_MAX_COL As Long = 53

Public Const PWRSEQ_INPUT_COL_NAME As Long = 1
Public Const PWRSEQ_INPUT_COL_SIDE As Long = 2
Public Const PWRSEQ_INPUT_COL_MODE As Long = 3
Public Const PWRSEQ_INPUT_COL_WAVE As Long = 4
Public Const PWRSEQ_INPUT_COL_OPERATION As Long = 5
Public Const PWRSEQ_INPUT_COL_GROUP_INV As Long = 6
Public Const PWRSEQ_INPUT_COL_SIGNAL_START As Long = 7
Public Const PWRSEQ_INPUT_MAX_COL As Long = 55

Private Const SIDE_HI As String = "Hi"
Private Const SIDE_LO As String = "Lo"
Private Const MODE_LOW As String = "Low (0)"
Private Const MODE_HIGH As String = "High (1)"
Private Const MODE_CUSTOM As String = "Custom wave"
Private Const MODE_DEPENDS As String = "Signal cond."

Private Const COND_TYPE_HI As String = "Hi"
Private Const COND_TYPE_LO As String = "Lo"
Private Const COND_TYPE_FORCE As String = "Force"
Private Const USE_SUFFIX_HI As String = "|Hi Cond"
Private Const USE_SUFFIX_LO As String = "|Lo Cond"
Private Const USE_SUFFIX_FORCE As String = "|Force Cond"

Private Const PWRSEQ_LISTS_PULSE_COL As Long = 2

Private gSyncing As Boolean
Private g_wsNodes As Worksheet
Private g_wsCond As Worksheet
Private g_wsInputCond As Worksheet
Private g_wsLists As Worksheet
Private g_wsConfig As Worksheet

Public Function IsSyncInProgress() As Boolean
    IsSyncInProgress = gSyncing
End Function

Public Sub SetSheetRefs()
    Dim ws As Worksheet

    Set g_wsNodes = Nothing
    Set g_wsCond = Nothing
    Set g_wsInputCond = Nothing
    Set g_wsLists = Nothing
    Set g_wsConfig = Nothing

    For Each ws In ThisWorkbook.Worksheets
        Select Case LCase$(Trim$(CStr(ws.Cells(1, 1).Value)))
            Case "name"
                Set g_wsNodes = ws
            Case "output_name"
                Set g_wsCond = ws
            Case "input_name"
                Set g_wsInputCond = ws
            Case "key"
                Set g_wsConfig = ws
        End Select
        If ws.Name = "Lists" Then Set g_wsLists = ws
    Next ws

    If g_wsConfig Is Nothing Then
        On Error Resume Next
        Set g_wsConfig = ThisWorkbook.Worksheets("Config")
        On Error GoTo 0
    End If
    If g_wsLists Is Nothing Then
        On Error Resume Next
        Set g_wsLists = ThisWorkbook.Worksheets("Lists")
        On Error GoTo 0
    End If

    If g_wsNodes Is Nothing Then Err.Raise vbObjectError + 1, , "Missing nodes sheet"
    If g_wsCond Is Nothing Then Err.Raise vbObjectError + 2, , "Missing cond sheet"
    If g_wsLists Is Nothing Then Err.Raise vbObjectError + 3, , "Missing Lists sheet"
    If g_wsInputCond Is Nothing Then Err.Raise vbObjectError + 4, , "Missing input cond sheet"
    If g_wsConfig Is Nothing Then Err.Raise vbObjectError + 5, , "Missing Config sheet"
End Sub

Public Sub RequestSyncFromNodes()
    If gSyncing Then Exit Sub
    gSyncing = True
    On Error GoTo Finally
    SyncPulseListFromConfig
    SetSheetRefs
    SyncOutputConditions
    SyncInputConditions
    SyncListsNodeNames
Finally:
    gSyncing = False
End Sub

Private Function IsOutputType(ByVal raw As Variant) As Boolean
    IsOutputType = (StrComp(Trim$(CStr(raw)), "Output", vbTextCompare) = 0)
End Function

Private Function IsInputType(ByVal raw As Variant) As Boolean
    IsInputType = (StrComp(Trim$(CStr(raw)), "Input", vbTextCompare) = 0)
End Function

Private Function CollectInputs(ByVal wsNodes As Worksheet) As Collection
    Dim inputs As New Collection
    Dim r As Long
    Dim name As String

    For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
        name = Trim$(CStr(wsNodes.Cells(r, 1).Value))
        If Len(name) > 0 And IsInputType(wsNodes.Cells(r, 2).Value) Then
            inputs.Add name
        End If
    Next r

    Set CollectInputs = inputs
End Function

Private Function CollectOutputs(ByVal wsNodes As Worksheet) As Collection
    Dim outputs As New Collection
    Dim r As Long
    Dim name As String

    For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
        name = Trim$(CStr(wsNodes.Cells(r, 1).Value))
        If Len(name) > 0 And IsOutputType(wsNodes.Cells(r, 2).Value) Then
            outputs.Add name
        End If
    Next r

    Set CollectOutputs = outputs
End Function

Private Function ResolveOutputName(ByVal wsCond As Worksheet, ByVal rowNum As Long, ByVal current As String) As String
  Dim r As Long
  Dim v As String

  v = Trim$(CStr(wsCond.Cells(rowNum, PWRSEQ_COND_COL_NAME).Value))
  If Len(v) > 0 Then
    ResolveOutputName = v
    Exit Function
  End If

  For r = rowNum - 1 To PWRSEQ_DATA_START_ROW Step -1
    v = Trim$(CStr(wsCond.Cells(r, PWRSEQ_COND_COL_NAME).Value))
    If Len(v) > 0 Then
      ResolveOutputName = v
      Exit Function
    End If
  Next r

  ResolveOutputName = current
End Function

Private Function NormalizeCondType(ByVal raw As Variant) As String
  Dim t As String
  t = Trim$(CStr(raw))
  If Len(t) = 0 Then Exit Function

  Select Case LCase$(t)
    Case "hi"
      NormalizeCondType = COND_TYPE_HI
    Case "lo"
      NormalizeCondType = COND_TYPE_LO
    Case "force"
      NormalizeCondType = COND_TYPE_FORCE
  End Select
End Function

Private Function NormalizeGroupInv(ByVal raw As Variant) As String
  Dim v As String
  v = UCase$(Trim$(CStr(raw)))
  If Len(v) = 0 Or v = "0" Or v = "N" Then
    NormalizeGroupInv = "N"
  ElseIf v = "1" Or v = "Y" Then
    NormalizeGroupInv = "Y"
  Else
    NormalizeGroupInv = "N"
  End If
End Function

Private Function IsLegacyGroupInvCell(ByVal raw As Variant) As Boolean
  Dim t As String
  t = UCase$(Trim$(CStr(raw)))
  If Len(t) = 0 Then
    IsLegacyGroupInvCell = True
    Exit Function
  End If
  If t = "Y" Or t = "N" Or t = "YES" Or t = "NO" Then
    IsLegacyGroupInvCell = True
  Else
    IsLegacyGroupInvCell = False
  End If
End Function

Private Function NormalizeOperation(ByVal raw As Variant) As String
  Dim t As String
  t = UCase$(Trim$(CStr(raw)))
  If Len(t) = 0 Then
    NormalizeOperation = "AND"
    Exit Function
  End If
  Select Case t
    Case "AND", "OR", "XOR"
      NormalizeOperation = t
    Case Else
      NormalizeOperation = "AND"
  End Select
End Function

Private Function CondLastCol() As Long
  Dim c As Long
  Dim last As Long
  Dim key As String

  last = PWRSEQ_COND_COL_SIGNAL_START
  For c = PWRSEQ_COND_COL_SIGNAL_START To PWRSEQ_COND_MAX_COL
    key = LCase$(Trim$(CStr(g_wsCond.Cells(1, c).Value)))
    If Left$(key, 6) = "signal" Then last = c
  Next c
  CondLastCol = last
End Function

Private Function RowHasCondData(ByVal wsCond As Worksheet, ByVal rowNum As Long) As Boolean
  Dim c As Long
  If Len(NormalizeCondType(wsCond.Cells(rowNum, PWRSEQ_COND_COL_TYPE).Value)) > 0 Then
    RowHasCondData = True
    Exit Function
  End If
  For c = PWRSEQ_COND_COL_SIGNAL_START To CondLastCol()
    If Len(Trim$(CStr(wsCond.Cells(rowNum, c).Value))) > 0 Then
      RowHasCondData = True
      Exit Function
    End If
  Next c
End Function

Private Sub EnsureTypeRow(ByVal rows As Collection, ByVal condType As String)
  Dim i As Long
  Dim rowType As String

  For i = 1 To rows.Count
    rowType = rows(i)(0)
    If rowType = condType Then Exit Sub
  Next i
  rows.Add Array(condType, "AND", "N", Empty)
End Sub

Private Sub LoadSavedOutputRows(ByVal outputName As String, ByVal rows As Collection)
  Dim r As Long
  Dim current As String
  Dim condType As String
  Dim operation As String
  Dim groupInv As String
  Dim signals As Variant
  Dim lastCol As Long
  Dim opCell As Variant

  lastCol = CondLastCol()
  current = ""
  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    current = ResolveOutputName(g_wsCond, r, current)
    If Len(current) = 0 Then Exit For
    If current <> outputName Then GoTo ContinueLoop
    If Not RowHasCondData(g_wsCond, r) Then GoTo ContinueLoop

    condType = NormalizeCondType(g_wsCond.Cells(r, PWRSEQ_COND_COL_TYPE).Value)
    If Len(condType) = 0 Then GoTo ContinueLoop
    opCell = g_wsCond.Cells(r, PWRSEQ_COND_COL_OPERATION).Value
    If IsLegacyGroupInvCell(opCell) Then
      operation = "AND"
      groupInv = NormalizeGroupInv(opCell)
    Else
      operation = NormalizeOperation(opCell)
      groupInv = NormalizeGroupInv(g_wsCond.Cells(r, PWRSEQ_COND_COL_GROUP_INV).Value)
    End If
    signals = g_wsCond.Range(g_wsCond.Cells(r, PWRSEQ_COND_COL_SIGNAL_START), g_wsCond.Cells(r, lastCol)).Value
    rows.Add Array(condType, operation, groupInv, signals)
ContinueLoop:
  Next r
End Sub

Private Sub WriteOutputBlock(ByVal outputName As String, ByVal rows As Collection, ByRef destRow As Long)
  Dim i As Long
  Dim blockStart As Long
  Dim condType As String
  Dim operation As String
  Dim groupInv As String
  Dim signals As Variant
  Dim lastCol As Long

  lastCol = CondLastCol()
  blockStart = destRow
  For i = 1 To rows.Count
    condType = rows(i)(0)
    operation = rows(i)(1)
    groupInv = rows(i)(2)
    signals = rows(i)(3)
    g_wsCond.Cells(destRow, PWRSEQ_COND_COL_TYPE).Value = condType
    g_wsCond.Cells(destRow, PWRSEQ_COND_COL_OPERATION).Value = operation
    g_wsCond.Cells(destRow, PWRSEQ_COND_COL_GROUP_INV).Value = groupInv
    If Not IsEmpty(signals) Then
      g_wsCond.Range(g_wsCond.Cells(destRow, PWRSEQ_COND_COL_SIGNAL_START), g_wsCond.Cells(destRow, lastCol)).Value = signals
    End If
    destRow = destRow + 1
  Next i

  g_wsCond.Cells(blockStart, PWRSEQ_COND_COL_NAME).Value = outputName
  If destRow - 1 > blockStart Then
    On Error Resume Next
    g_wsCond.Range(g_wsCond.Cells(blockStart, PWRSEQ_COND_COL_NAME), g_wsCond.Cells(destRow - 1, PWRSEQ_COND_COL_NAME)).Merge
    On Error GoTo 0
  End If
End Sub

Private Sub ClearCondDataArea()
  On Error Resume Next
  g_wsCond.Range(g_wsCond.Cells(PWRSEQ_DATA_START_ROW, 1), g_wsCond.Cells(PWRSEQ_MAX_ROW, CondLastCol())).UnMerge
  On Error GoTo 0
  g_wsCond.Range(g_wsCond.Cells(PWRSEQ_DATA_START_ROW, 1), g_wsCond.Cells(PWRSEQ_MAX_ROW, CondLastCol())).ClearContents
End Sub

Public Sub SyncOutputConditions()
  Dim savedOutputs As Object
  Dim outputs As Collection
  Dim rows As Collection
  Dim destRow As Long
  Dim i As Long
  Dim r As Long
  Dim name As String

  Set savedOutputs = CreateObject("Scripting.Dictionary")
  Set outputs = CollectOutputs(g_wsNodes)

  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    name = ResolveOutputName(g_wsCond, r, "")
    If Len(name) = 0 Then Exit For
    If Not savedOutputs.Exists(name) Then
      Set rows = New Collection
      LoadSavedOutputRows name, rows
      savedOutputs.Add name, rows
    End If
  Next r

  ClearCondDataArea
  destRow = PWRSEQ_DATA_START_ROW
  For i = 1 To outputs.Count
    name = outputs(i)
    If savedOutputs.Exists(name) Then
      Set rows = savedOutputs(name)
    Else
      Set rows = New Collection
    End If
    EnsureTypeRow rows, COND_TYPE_HI
    EnsureTypeRow rows, COND_TYPE_LO
    EnsureTypeRow rows, COND_TYPE_FORCE
    SortRowsByType rows
    WriteOutputBlock name, rows, destRow
  Next i
End Sub

Private Sub SortRowsByType(ByVal rows As Collection)
  Dim hiRows As New Collection
  Dim loRows As New Collection
  Dim forceRows As New Collection
  Dim otherRows As New Collection
  Dim i As Long
  Dim condType As String

  For i = 1 To rows.Count
    condType = rows(i)(0)
    Select Case condType
      Case COND_TYPE_HI: hiRows.Add rows(i)
      Case COND_TYPE_LO: loRows.Add rows(i)
      Case COND_TYPE_FORCE: forceRows.Add rows(i)
      Case Else: otherRows.Add rows(i)
    End Select
  Next i

  Do While rows.Count > 0
    rows.Remove 1
  Loop
  For i = 1 To hiRows.Count: rows.Add hiRows(i): Next i
  For i = 1 To loRows.Count: rows.Add loRows(i): Next i
  For i = 1 To forceRows.Count: rows.Add forceRows(i): Next i
  For i = 1 To otherRows.Count: rows.Add otherRows(i): Next i
End Sub

Private Function InputCondLastCol() As Long
  Dim c As Long
  Dim last As Long
  Dim key As String

  last = PWRSEQ_INPUT_COL_SIGNAL_START
  For c = PWRSEQ_INPUT_COL_SIGNAL_START To PWRSEQ_INPUT_MAX_COL
    key = LCase$(Trim$(CStr(g_wsInputCond.Cells(1, c).Value)))
    If Left$(key, 6) = "signal" Then last = c
  Next c
  InputCondLastCol = last
End Function

Private Function NormalizeSide(ByVal raw As Variant) As String
  Dim t As String
  t = Trim$(CStr(raw))
  If Len(t) = 0 Then Exit Function
  Select Case LCase$(t)
    Case "hi"
      NormalizeSide = SIDE_HI
    Case "lo"
      NormalizeSide = SIDE_LO
  End Select
End Function

Private Function NormalizeInputMode(ByVal raw As Variant) As String
  Dim t As String
  t = Trim$(CStr(raw))
  If Len(t) = 0 Then Exit Function
  Select Case t
    Case MODE_LOW, MODE_HIGH, MODE_CUSTOM, MODE_DEPENDS
      NormalizeInputMode = t
    Case Else
      Select Case LCase$(t)
        Case "low (0)", "low", "0", "constant_0"
          NormalizeInputMode = MODE_LOW
        Case "high (1)", "high", "1", "constant_1"
          NormalizeInputMode = MODE_HIGH
        Case "custom wave", "custom"
          NormalizeInputMode = MODE_CUSTOM
        Case "signal cond.", "depends", "signal cond"
          NormalizeInputMode = MODE_DEPENDS
      End Select
  End Select
End Function

Private Function ResolveInputName(ByVal wsInput As Worksheet, ByVal rowNum As Long, ByVal current As String) As String
  Dim r As Long
  Dim v As String

  v = Trim$(CStr(wsInput.Cells(rowNum, PWRSEQ_INPUT_COL_NAME).Value))
  If Len(v) > 0 Then
    ResolveInputName = v
    Exit Function
  End If

  For r = rowNum - 1 To PWRSEQ_DATA_START_ROW Step -1
    v = Trim$(CStr(wsInput.Cells(r, PWRSEQ_INPUT_COL_NAME).Value))
    If Len(v) > 0 Then
      ResolveInputName = v
      Exit Function
    End If
  Next r

  ResolveInputName = current
End Function

Private Function RowHasInputCondData(ByVal wsInput As Worksheet, ByVal rowNum As Long) As Boolean
  Dim c As Long
  If Len(NormalizeSide(wsInput.Cells(rowNum, PWRSEQ_INPUT_COL_SIDE).Value)) > 0 Then
    RowHasInputCondData = True
    Exit Function
  End If
  If Len(NormalizeInputMode(wsInput.Cells(rowNum, PWRSEQ_INPUT_COL_MODE).Value)) > 0 Then
    RowHasInputCondData = True
    Exit Function
  End If
  If Len(Trim$(CStr(wsInput.Cells(rowNum, PWRSEQ_INPUT_COL_WAVE).Value))) > 0 Then
    RowHasInputCondData = True
    Exit Function
  End If
  For c = PWRSEQ_INPUT_COL_SIGNAL_START To InputCondLastCol()
    If Len(Trim$(CStr(wsInput.Cells(rowNum, c).Value))) > 0 Then
      RowHasInputCondData = True
      Exit Function
    End If
  Next c
End Function

Private Sub EnsureInputSideRow(ByVal rows As Collection, ByVal side As String, ByVal defaultMode As String)
  Dim i As Long
  Dim rowSide As String

  For i = 1 To rows.Count
    rowSide = rows(i)(0)
    If rowSide = side Then Exit Sub
  Next i
  rows.Add Array(side, defaultMode, Empty, "AND", "N", Empty)
End Sub

Private Sub LoadSavedInputRows(ByVal inputName As String, ByVal rows As Collection)
  Dim r As Long
  Dim current As String
  Dim side As String
  Dim mode As String
  Dim waveVal As Variant
  Dim operation As String
  Dim groupInv As String
  Dim signals As Variant
  Dim lastCol As Long
  Dim opCell As Variant

  lastCol = InputCondLastCol()
  current = ""
  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    current = ResolveInputName(g_wsInputCond, r, current)
    If Len(current) = 0 Then Exit For
    If current <> inputName Then GoTo ContinueInputLoop
    If Not RowHasInputCondData(g_wsInputCond, r) Then GoTo ContinueInputLoop

    side = NormalizeSide(g_wsInputCond.Cells(r, PWRSEQ_INPUT_COL_SIDE).Value)
    If Len(side) = 0 Then GoTo ContinueInputLoop
    mode = NormalizeInputMode(g_wsInputCond.Cells(r, PWRSEQ_INPUT_COL_MODE).Value)
    If Len(mode) = 0 Then mode = MODE_DEPENDS
    waveVal = g_wsInputCond.Cells(r, PWRSEQ_INPUT_COL_WAVE).Value
    opCell = g_wsInputCond.Cells(r, PWRSEQ_INPUT_COL_OPERATION).Value
    If IsLegacyGroupInvCell(opCell) Then
      operation = "AND"
      groupInv = NormalizeGroupInv(opCell)
    Else
      operation = NormalizeOperation(opCell)
      groupInv = NormalizeGroupInv(g_wsInputCond.Cells(r, PWRSEQ_INPUT_COL_GROUP_INV).Value)
    End If
    signals = g_wsInputCond.Range(g_wsInputCond.Cells(r, PWRSEQ_INPUT_COL_SIGNAL_START), g_wsInputCond.Cells(r, lastCol)).Value
    rows.Add Array(side, mode, waveVal, operation, groupInv, signals)
ContinueInputLoop:
  Next r
End Sub

Private Sub WriteInputBlock(ByVal inputName As String, ByVal rows As Collection, ByRef destRow As Long)
  Dim i As Long
  Dim blockStart As Long
  Dim side As String
  Dim mode As String
  Dim waveVal As Variant
  Dim operation As String
  Dim groupInv As String
  Dim signals As Variant
  Dim lastCol As Long

  lastCol = InputCondLastCol()
  blockStart = destRow
  For i = 1 To rows.Count
    side = rows(i)(0)
    mode = rows(i)(1)
    waveVal = rows(i)(2)
    operation = rows(i)(3)
    groupInv = rows(i)(4)
    signals = rows(i)(5)
    g_wsInputCond.Cells(destRow, PWRSEQ_INPUT_COL_SIDE).Value = side
    g_wsInputCond.Cells(destRow, PWRSEQ_INPUT_COL_MODE).Value = mode
    g_wsInputCond.Cells(destRow, PWRSEQ_INPUT_COL_WAVE).Value = waveVal
    g_wsInputCond.Cells(destRow, PWRSEQ_INPUT_COL_OPERATION).Value = operation
    g_wsInputCond.Cells(destRow, PWRSEQ_INPUT_COL_GROUP_INV).Value = groupInv
    If Not IsEmpty(signals) Then
      g_wsInputCond.Range(g_wsInputCond.Cells(destRow, PWRSEQ_INPUT_COL_SIGNAL_START), g_wsInputCond.Cells(destRow, lastCol)).Value = signals
    End If
    destRow = destRow + 1
  Next i

  g_wsInputCond.Cells(blockStart, PWRSEQ_INPUT_COL_NAME).Value = inputName
  If destRow - 1 > blockStart Then
    On Error Resume Next
    g_wsInputCond.Range(g_wsInputCond.Cells(blockStart, PWRSEQ_INPUT_COL_NAME), g_wsInputCond.Cells(destRow - 1, PWRSEQ_INPUT_COL_NAME)).Merge
    On Error GoTo 0
  End If
End Sub

Private Sub ClearInputCondDataArea()
  On Error Resume Next
  g_wsInputCond.Range(g_wsInputCond.Cells(PWRSEQ_DATA_START_ROW, 1), g_wsInputCond.Cells(PWRSEQ_MAX_ROW, InputCondLastCol())).UnMerge
  On Error GoTo 0
  g_wsInputCond.Range(g_wsInputCond.Cells(PWRSEQ_DATA_START_ROW, 1), g_wsInputCond.Cells(PWRSEQ_MAX_ROW, InputCondLastCol())).ClearContents
End Sub

Private Sub SortInputRowsBySide(ByVal rows As Collection)
  Dim hiRows As New Collection
  Dim loRows As New Collection
  Dim otherRows As New Collection
  Dim i As Long
  Dim side As String

  For i = 1 To rows.Count
    side = rows(i)(0)
    Select Case side
      Case SIDE_HI: hiRows.Add rows(i)
      Case SIDE_LO: loRows.Add rows(i)
      Case Else: otherRows.Add rows(i)
    End Select
  Next i

  Do While rows.Count > 0
    rows.Remove 1
  Loop
  For i = 1 To hiRows.Count: rows.Add hiRows(i): Next i
  For i = 1 To loRows.Count: rows.Add loRows(i): Next i
  For i = 1 To otherRows.Count: rows.Add otherRows(i): Next i
End Sub

Public Sub SyncInputConditions()
  Dim savedInputs As Object
  Dim inputs As Collection
  Dim rows As Collection
  Dim destRow As Long
  Dim i As Long
  Dim r As Long
  Dim name As String

  Set savedInputs = CreateObject("Scripting.Dictionary")
  Set inputs = CollectInputs(g_wsNodes)

  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    name = ResolveInputName(g_wsInputCond, r, "")
    If Len(name) = 0 Then Exit For
    If Not savedInputs.Exists(name) Then
      Set rows = New Collection
      LoadSavedInputRows name, rows
      savedInputs.Add name, rows
    End If
  Next r

  ClearInputCondDataArea
  destRow = PWRSEQ_DATA_START_ROW
  For i = 1 To inputs.Count
    name = inputs(i)
    If savedInputs.Exists(name) Then
      Set rows = savedInputs(name)
    Else
      Set rows = New Collection
    End If
    EnsureInputSideRow rows, SIDE_HI, MODE_DEPENDS
    EnsureInputSideRow rows, SIDE_LO, MODE_LOW
    SortInputRowsBySide rows
    WriteInputBlock name, rows, destRow
  Next i
End Sub

Private Sub UpdateSignalList(ByVal lastRow As Long)
  UpdateNamedList "SignalList", 1, lastRow
End Sub

Private Sub UpdatePulseList(ByVal lastRow As Long)
  UpdateNamedList "PulseList", PWRSEQ_LISTS_PULSE_COL, lastRow
End Sub

Private Sub UpdateNamedList(ByVal listName As String, ByVal colNum As Long, ByVal lastRow As Long)
  Dim refersTo As String
  Dim colLetter As String

  If lastRow < 2 Then lastRow = 2
  colLetter = Split(g_wsLists.Cells(1, colNum).Address(True, False), "$")(0)
  refersTo = "='Lists'!$" & colLetter & "$2:$" & colLetter & "$" & lastRow
  On Error Resume Next
  ThisWorkbook.Names(listName).RefersTo = refersTo
  If Err.Number <> 0 Then
    Err.Clear
    ThisWorkbook.Names.Add Name:=listName, RefersTo:=refersTo
  End If
  On Error GoTo 0
End Sub

Private Function ConfigValueByKey(ByVal key As String) As String
  Dim ws As Worksheet
  Dim r As Long

  On Error Resume Next
  Set ws = ThisWorkbook.Worksheets("Config")
  On Error GoTo 0
  If ws Is Nothing Then Exit Function
  For r = 1 To 50
    If LCase$(Trim$(CStr(ws.Cells(r, 1).Value))) = LCase$(key) Then
      ConfigValueByKey = Trim$(CStr(ws.Cells(r, 4).Value))
      Exit Function
    End If
  Next r
End Function

Private Sub ParsePulseCsv(ByVal csv As String, ByVal pulses As Collection)
  Dim parts() As String
  Dim i As Long
  Dim p As String

  parts = Split(csv, ",")
  For i = LBound(parts) To UBound(parts)
    p = Trim$(parts(i))
    If Len(p) > 0 Then pulses.Add p
  Next i
End Sub

Public Sub SyncPulseListFromConfig()
  Dim csv As String
  Dim pulses As New Collection
  Dim clearToRow As Long
  Dim nextRow As Long
  Dim i As Long

  On Error Resume Next
  Set g_wsLists = ThisWorkbook.Worksheets("Lists")
  On Error GoTo 0
  If g_wsLists Is Nothing Then Exit Sub

  csv = ConfigValueByKey("pulses")
  If Len(csv) = 0 Then csv = ConfigValueByKey("default_pulse")
  If Len(csv) = 0 Then csv = "Pulse_1us"

  ParsePulseCsv csv, pulses
  If pulses.Count = 0 Then pulses.Add "Pulse_1us"

  clearToRow = g_wsLists.Cells(g_wsLists.Rows.Count, PWRSEQ_LISTS_PULSE_COL).End(xlUp).Row
  If clearToRow < 2 Then clearToRow = 2
  g_wsLists.Range( _
    g_wsLists.Cells(2, PWRSEQ_LISTS_PULSE_COL), _
    g_wsLists.Cells(clearToRow, PWRSEQ_LISTS_PULSE_COL)).ClearContents

  nextRow = 2
  For i = 1 To pulses.Count
    g_wsLists.Cells(nextRow, PWRSEQ_LISTS_PULSE_COL).Value = CStr(pulses(i))
    nextRow = nextRow + 1
  Next i

  If nextRow <= 2 Then nextRow = 3
  UpdatePulseList nextRow - 1
End Sub

Private Sub CollectListPresets(ByVal presets As Collection)
  Dim r As Long
  Dim name As String
  Dim seen As Object

  Set seen = CreateObject("Scripting.Dictionary")
  For r = 2 To 3
    name = Trim$(CStr(g_wsLists.Cells(r, 1).Value))
    If Len(name) > 0 And Not seen.Exists(name) Then
      seen.Add name, True
      presets.Add name
    End If
  Next r
End Sub

Private Sub AppendUniqueName(ByVal known As Object, ByRef nextRow As Long, ByVal name As String)
  If Len(name) = 0 Then Exit Sub
  If known.Exists(name) Then Exit Sub
  known.Add name, True
  g_wsLists.Cells(nextRow, 1).Value = name
  nextRow = nextRow + 1
End Sub

Private Sub AppendSignalsFromCondSheet(ByVal known As Object, ByRef nextRow As Long)
  Dim r As Long
  Dim c As Long
  Dim sig As String

  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    If Not RowHasCondData(g_wsCond, r) Then GoTo NextRow
    For c = PWRSEQ_COND_COL_SIGNAL_START To CondLastCol()
      sig = Trim$(CStr(g_wsCond.Cells(r, c).Value))
      AppendUniqueName known, nextRow, sig
    Next c
NextRow:
  Next r
End Sub

Private Sub AppendSignalsFromInputCondSheet(ByVal known As Object, ByRef nextRow As Long)
  Dim r As Long
  Dim c As Long
  Dim sig As String

  If g_wsInputCond Is Nothing Then Exit Sub
  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    If Not RowHasInputCondData(g_wsInputCond, r) Then GoTo NextInputRow
    For c = PWRSEQ_INPUT_COL_SIGNAL_START To InputCondLastCol()
      sig = Trim$(CStr(g_wsInputCond.Cells(r, c).Value))
      AppendUniqueName known, nextRow, sig
    Next c
NextInputRow:
  Next r
End Sub

Public Sub SyncListsNodeNames()
  Dim presets As New Collection
  Dim known As Object
  Dim r As Long
  Dim name As String
  Dim nextRow As Long
  Dim clearToRow As Long

  CollectListPresets presets
  Set known = CreateObject("Scripting.Dictionary")

  clearToRow = Application.WorksheetFunction.Max( _
    g_wsLists.Cells(g_wsLists.Rows.Count, 1).End(xlUp).Row, _
    PWRSEQ_MAX_ROW)
  If clearToRow < 2 Then clearToRow = 2
  g_wsLists.Range(g_wsLists.Cells(2, 1), g_wsLists.Cells(clearToRow, 1)).ClearContents

  nextRow = 2
  For r = 1 To presets.Count
    AppendUniqueName known, nextRow, CStr(presets(r))
  Next r

  For r = PWRSEQ_DATA_START_ROW To PWRSEQ_MAX_ROW
    name = Trim$(CStr(g_wsNodes.Cells(r, 1).Value))
    AppendUniqueName known, nextRow, name
    If Len(name) > 0 And IsOutputType(g_wsNodes.Cells(r, 2).Value) Then
      AppendUniqueName known, nextRow, name & USE_SUFFIX_HI
      AppendUniqueName known, nextRow, name & USE_SUFFIX_LO
      AppendUniqueName known, nextRow, name & USE_SUFFIX_FORCE
    End If
  Next r

  AppendSignalsFromCondSheet known, nextRow
  AppendSignalsFromInputCondSheet known, nextRow

  If nextRow <= 2 Then nextRow = 3
  UpdateSignalList nextRow - 1
End Sub

Public Sub SyncAllFromNodes()
  SyncPulseListFromConfig
  SyncOutputConditions
  SyncInputConditions
  SyncListsNodeNames
End Sub
