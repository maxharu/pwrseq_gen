Attribute VB_Name = "SheetConfig"
Option Explicit

Private Sub Worksheet_Change(ByVal Target As Range)
    Dim cell As Range

    If IsSyncInProgress() Then Exit Sub

    For Each cell In Target.Cells
        If cell.Column = 4 Then
            If LCase$(Trim$(CStr(Me.Cells(cell.Row, 1).Value))) = "pulses" Then
                Application.EnableEvents = False
                On Error GoTo Restore
                SyncPulseListFromConfig
Restore:
                Application.EnableEvents = True
                Exit Sub
            End If
        End If
    Next cell
End Sub
