`timescale 1ns / 1ps
////////////////////////////////////////////////////////////////////////////////
// Module                : PSEQCELL                                           //
// Author                : Haru Chen                                          //
// Date Simulation Tested:                                                    //
//                                                                            //
// Function Description  :                                                    //
//   Power Sequence Cell. The condition to output high/low is independent.    //
//   Parameter:                                                               //
//     WIDTH: bit width                                                       //
//     CYCLE_HI: Number of cycle for high condition.                          //
//     CYCLE_LO: Number of cycle for low  condition.                          //
//     CYCLE_FORCE: Number of cycle for force debounce.                       //
//     RECOVER: Recover Function, output can recover when even conditon keep  //
//         asserted. b0/b1 for low/high condition.                            //
//         0: wait for the L/H conditon deassertion when current output L/H   //
//         1: didn't wait for the condition deassertion.                      //
//     INIT: Initial output state.                                            //
//     FORCE: Force output state when Force assertion.                        //
//     CYCLE_SYNC: Number of sync cycle for iHi/iLo.                          //
//     OD: tyep of output. 0: Push-pull, 1: Open-drain                        //
//   IO:                                                                      //
//     iPulse_Hi: Sample Pulse for iHi.                                       //
//     iPulse_Lo: Sample Pulse for iLo.                                       //
//     iPulse_Force: Sample Pulse for iForce debounce.                        //
//     iForce:  Force Output signal                                           //
//     o: Output                                                              //
//                                                                            //
// Change Log            :                                                    //
// 2025-07-16                                                                 //
//   Add Parameter CYCLE_FORCE for iForce                                     //
//   Add iPulse_Force                                                         //
//   Rename iForceOn to iForce                                                //
// 2025-07-12                                                                 //
//   Rename SYNC to CYCLE_SYNC. Rename oOut to o.                             //
// 2024-11-12                                                                 //
//   Rename RST to INIT                                                       //
// 2023-11-15                                                                 //
//   Integrate RECOVERY_HI and RECOVERY_LO into RECOVER                       //
// 2023-10-27                                                                 //
//   Add parameter RECOVERY_HI, RECOVERY_LO                                   //
// 2023-10-25                                                                 //
//   Initial design.                                                          //
////////////////////////////////////////////////////////////////////////////////
`ifndef PSEQCELL_V
`define PSEQCELL_V

////////////////////////////////////////////////////////////////////////////////
// Define                                                                     //
////////////////////////////////////////////////////////////////////////////////
//`define DEFINE_NAME    0

////////////////////////////////////////////////////////////////////////////////
// Library Include                                                            //
////////////////////////////////////////////////////////////////////////////////
`ifndef PSEQ_LIB
//    `include "../../MYLIB/Source/myLib.v"
`endif //PSEQ_LIB

////////////////////////////////////////////////////////////////////////////////
// Module Declare                                                             //
////////////////////////////////////////////////////////////////////////////////
module PSEQCELL
////////////////////////////////////////////////////////////////////////////////
// Parameter Declare                                                          //
////////////////////////////////////////////////////////////////////////////////
#(
    parameter WIDTH      = 1,
    parameter CYCLE_HI   = 3,
    parameter CYCLE_LO   = 2,
    parameter CYCLE_FORCE= 2,
    parameter [1:0]RECOVER = 2'b11,     //b0:Recover for Low condition, b1:Recover for High condition.
    parameter INIT       = 0,           //0: Output Low when Reset,   1: Output High when Reset
    parameter FORCE      = 0,           //0: Output Low when Force, 1: Output High when Force
    parameter CYCLE_SYNC = 0,           //The number of sync cycle for iHi/iLo
    parameter OD         = 0            //0: Push-pull (1->High, 0->Low), 1: Open-Drain (1->HiZ, 0->Low)
)
////////////////////////////////////////////////////////////////////////////////
// Input/Output Port Declare                                                  //
////////////////////////////////////////////////////////////////////////////////
(
    input  iRst, iClk_Core, 
    input  iPulse_Hi, iPulse_Lo,        //Sample Pulse for Hi and Lo condition
    input  iPulse_Force,
    input  [WIDTH-1:0]iHi, iLo,         //Condition to trigger Out high and low
    input  [WIDTH-1:0]iForce,           //Force Output
    output [WIDTH-1:0]o                 //Out
);

////////////////////////////////////////////////////////////////////////////////
// Function Include                                                           //
////////////////////////////////////////////////////////////////////////////////
function integer max (input integer val_a, val_b);
    max = (val_a>val_b) ? val_a : val_b;
endfunction

////////////////////////////////////////////////////////////////////////////////
// Local Parameter Declare                                                    //
////////////////////////////////////////////////////////////////////////////////
//SM
//localparam ST_IDLE = 0;
//localparam LAST_ST = ST_IDLE;

////////////////////////////////////////////////////////////////////////////////
// Internal Signal Declare                                                    //
////////////////////////////////////////////////////////////////////////////////
reg  [WIDTH-1:0]rHiPermit, rLoPermit;
reg  [WIDTH-1:0]rOut;
wire [WIDTH-1:0]wHi, wLo;
wire [WIDTH-1:0]wForce, wForceSync;

reg [max(CYCLE_HI, CYCLE_LO)-1:0]rPipe[WIDTH-1:0];

genvar gv;
integer i;
////////////////////////////////////////////////////////////////////////////////
// Task Define                                                                //
////////////////////////////////////////////////////////////////////////////////
//task tskTASK_NAME(input i);
//begin
//    
//end
//endtask

////////////////////////////////////////////////////////////////////////////////
// Design                                                                     //
////////////////////////////////////////////////////////////////////////////////
///// Instance /////////////////////////////////////////////////////////////////

///// Always Block /////////////////////////////////////////////////////////////
generate
if (CYCLE_SYNC) begin
    reg  [CYCLE_SYNC-1:0]rSyncHi[WIDTH-1:0], rSyncLo[WIDTH-1:0], rSyncForce[WIDTH-1:0];
    always @(posedge iClk_Core or posedge iRst) begin
        if (iRst) begin
            for (i=0; i<WIDTH; i=i+1) begin
                rSyncHi[i]    <= #1 {CYCLE_SYNC{1'b0}};
                rSyncLo[i]    <= #1 {CYCLE_SYNC{1'b0}};
                rSyncForce[i] <= #1 {CYCLE_SYNC{1'b0}};
            end
        end else begin
            for (i=0; i<WIDTH; i=i+1) begin
                rSyncHi[i]    <= #1 {rSyncHi[i], iHi[i]};
                rSyncLo[i]    <= #1 {rSyncLo[i], iLo[i]};
                rSyncForce[i] <= #1 {rSyncForce[i], iForce[i]};
            end
        end
    end
    for (gv=0; gv<WIDTH; gv=gv+1) begin
        assign wHi[gv]        = rSyncHi[gv][CYCLE_SYNC-1];
        assign wLo[gv]        = rSyncLo[gv][CYCLE_SYNC-1];
        assign wForceSync[gv] = rSyncForce[gv][CYCLE_SYNC-1];
    end
end else begin
    assign {wHi, wLo, wForceSync} = {iHi, iLo, iForce};
end

if (CYCLE_FORCE) begin
    reg [CYCLE_FORCE-1:0]rForce_Pipe[WIDTH-1:0];
    reg [WIDTH-1:0]rForce_Deb;
    always @(posedge iClk_Core or posedge iRst) begin
        if (iRst) begin
            for (i=0; i<WIDTH; i=i+1) begin
                rForce_Pipe[i] <= #1 {CYCLE_FORCE{1'b0}};
            end
        end else begin
            for (i=0; i<WIDTH; i=i+1) begin
                if (iPulse_Force) begin
                    rForce_Pipe[i] <= #1 {rForce_Pipe[i], wForceSync[i]};
                end
                if (&rForce_Pipe[i]) rForce_Deb[i] <= #1 1'b1;
                else                 rForce_Deb[i] <= #1 1'b0;
            end
        end
    end
    assign wForce = rForce_Deb;
end else begin
    assign wForce = wForceSync;
end

for (gv=0; gv<WIDTH; gv=gv+1) begin
    always @(posedge iClk_Core) begin: PERMIT //avoid output toggle at both conditions are high.
        if (iRst) begin
            rHiPermit[gv] <= #1 1'b1;
            rLoPermit[gv] <= #1 1'b1;
        end else begin
            if (!rOut[gv]) begin
                rLoPermit[gv] <= #1 0;
                if (RECOVER[1]) rHiPermit[gv] <= #1 (!wHi[gv] || !wLo[gv]) ? 1'b1 : rHiPermit[gv];
                else            rHiPermit[gv] <= #1 (!wHi[gv])             ? 1'b1 : rHiPermit[gv];
            end else begin
                rHiPermit[gv] <= #1 0;
                if (RECOVER[0]) rLoPermit[gv] <= #1 (!wLo[gv] || !wHi[gv]) ? 1'b1 : rLoPermit[gv];
                else            rLoPermit[gv] <= #1 (!wLo[gv])             ? 1'b1 : rLoPermit[gv];
            end
        end
    end
    
    always @(posedge iClk_Core) begin: OUT
        if (iRst) begin
            rOut[gv] <= #1 (INIT ) ? 1'b1 : 1'b0;
            rPipe[gv]<= #1 (INIT ) ? {(max(CYCLE_HI, CYCLE_LO)){1'b1}} : {(max(CYCLE_HI, CYCLE_LO)){1'b0}};
        end else if (wForce[gv]) begin
            rOut[gv] <= #1 (FORCE) ? 1'b1 : 1'b0;
            rPipe[gv]<= #1 (FORCE) ? {(max(CYCLE_HI, CYCLE_LO)){1'b1}} : {(max(CYCLE_HI, CYCLE_LO)){1'b0}};
        end else begin
            if (!rOut[gv]) begin
                if (rHiPermit[gv] && wHi[gv]) rPipe[gv] <= #1 (iPulse_Hi) ? {rPipe[gv],  1'b1} : rPipe[gv];
                else                          rPipe[gv] <= #1 (iPulse_Lo) ? {rPipe[gv],  1'b0} : rPipe[gv];
            end else begin
                if (rLoPermit[gv] && wLo[gv]) rPipe[gv] <= #1 (iPulse_Lo) ? {rPipe[gv],  1'b0} : rPipe[gv];
                else                          rPipe[gv] <= #1 (iPulse_Hi) ? {rPipe[gv],  1'b1} : rPipe[gv];
            end
            
            if      ((&rPipe[gv][CYCLE_HI-1:0])==1'b1) rOut[gv] <= #1 1'b1;
            else if ((|rPipe[gv][CYCLE_LO-1:0])==1'b0) rOut[gv] <= #1 1'b0;
        end
    end
end

///// Continuous Assignment ////////////////////////////////////////////////////
for (gv=0; gv<WIDTH; gv=gv+1) begin
    assign o[gv] = rOut[gv] ? (OD ? 1'bz : 1'b1) : 1'b0;
end
endgenerate

endmodule //PSEQCELL
`endif  //PSEQCELL_V
