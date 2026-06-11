Option Explicit

' Output/Input conditions and Lists: manual Sync button.
' On open: sync Config pulses -> Lists PulseList (Nodes dropdown source).
Private Sub Workbook_Open()
    On Error Resume Next
    SyncPulseListFromConfig
End Sub
