`timescale 1ns / 1ps
////////////////////////////////////////////////////////////////////////////////
// Module                : test                                               //
// Author                : pwrseq_gen (Auto-generated)                        //
// Date Simulation Tested:                                                    //
//                                                                            //
// Function Description  :                                                    //
//   Power Sequence. output: oXXX, input: iXXX.                               //
//   iHi from depends_on (output: out, input: in). iLo default 1'b0.          //
// Change Log            :                                                    //
//   Auto-generated.                                                           //
////////////////////////////////////////////////////////////////////////////////
`ifndef TEST_V
`define TEST_V

////////////////////////////////////////////////////////////////////////////////
// Define                                                                     //
////////////////////////////////////////////////////////////////////////////////
//`define DEFINE_NAME    0

////////////////////////////////////////////////////////////////////////////////
// Library Include                                                            //
////////////////////////////////////////////////////////////////////////////////
//`include "PSEQCELL.v"

////////////////////////////////////////////////////////////////////////////////
// Module Declare                                                             //
////////////////////////////////////////////////////////////////////////////////
module test
////////////////////////////////////////////////////////////////////////////////
// Parameter Declare                                                          //
////////////////////////////////////////////////////////////////////////////////
#(
    // No parameters
)
////////////////////////////////////////////////////////////////////////////////
// Input/Output Port Declare                                                  //
////////////////////////////////////////////////////////////////////////////////
(
    input  iRst,
    input  iClk_Core,
    input  iPulse_1us,
    input  iIN1,
    output oOUT1,
    output oOUT2,
    output oOUT3,
    input  iIN2,
    input  iForce  // Optional: tie to 0 if not used
);

////////////////////////////////////////////////////////////////////////////////
// Function Include                                                           //
////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////
// Local Parameter Declare                                                    //
////////////////////////////////////////////////////////////////////////////////
// None

////////////////////////////////////////////////////////////////////////////////
// Internal Signal Declare                                                    //
////////////////////////////////////////////////////////////////////////////////
wire in1_deb;
wire out1;
wire out2;
wire out3;
wire in2_deb;

// Condition signals (iHi, iLo) for PSEQCELL
wire out1_hi;
wire out1_lo;
wire out2_hi;
wire out2_lo;
wire out3_hi;
wire out3_lo;

////////////////////////////////////////////////////////////////////////////////
// Task Define                                                                //
////////////////////////////////////////////////////////////////////////////////
// None

////////////////////////////////////////////////////////////////////////////////
// Design                                                                     //
////////////////////////////////////////////////////////////////////////////////
///// Instance /////////////////////////////////////////////////////////////////
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_in1 (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iIN1), .o(in1_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_in2 (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iIN2), .o(in2_deb));

    assign out1_hi = (in1_deb);
    assign out1_lo = (~(out2));
    assign out2_hi = (out1 & out1_hi);
    assign out2_lo = (~(out3)) || (~(in2_deb));
    assign out3_hi = (out2_hi & out2);
    assign out3_lo = (~(in2_deb));

    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_out1 (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(out1_hi), .iLo(out1_lo), .iForce(iForce), .o(out1));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_out2 (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(out2_hi), .iLo(out2_lo), .iForce(iForce), .o(out2));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(4), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_out3 (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(out3_hi), .iLo(out3_lo), .iForce(iForce), .o(out3));
///// Always Block /////////////////////////////////////////////////////////////
    // None

///// Continuous Assignment ////////////////////////////////////////////////////
    assign oOUT1 = out1;
    assign oOUT2 = out2;
    assign oOUT3 = out3;

endmodule //test
`endif  //TEST_V