`timescale 1ns / 1ps
////////////////////////////////////////////////////////////////////////////////
// Module                : mg204_pseq                                         //
// Author                : pwrseq_gen (Auto-generated)                        //
// Date Simulation Tested:                                                    //
//                                                                            //
// Function Description  :                                                    //
//   Power Sequence. output: oXXX, input: iXXX.                               //
//   iHi from depends_on (output: out, input: in). iLo default 1'b0.          //
// Change Log            :                                                    //
//   Auto-generated.                                                           //
////////////////////////////////////////////////////////////////////////////////
`ifndef MG204_PSEQ_V
`define MG204_PSEQ_V

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
module mg204_pseq
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
    input  iPS_PWOK,
    input  iP5V_PG,
    input  iP3V3_PG,
    input  iP1V8_PG,
    output oP5V_EN,
    output oP3V3_EN,
    output oP1V8_EN,
    output oP1V1_HUB_EN
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
wire ps_pwok_deb;
wire p5v_pg_deb;
wire p3v3_pg_deb;
wire p1v8_pg_deb;
wire p5v_en;
wire p3v3_en;
wire p1v8_en;
wire p1v1_hub_en;

// Condition signals (iHi, iLo, iForce) for PSEQCELL
wire p5v_en_hi;
wire p5v_en_lo;
wire p5v_en_force;
wire p3v3_en_hi;
wire p3v3_en_lo;
wire p3v3_en_force;
wire p1v8_en_hi;
wire p1v8_en_lo;
wire p1v8_en_force;
wire p1v1_hub_en_hi;
wire p1v1_hub_en_lo;
wire p1v1_hub_en_force;

////////////////////////////////////////////////////////////////////////////////
// Task Define                                                                //
////////////////////////////////////////////////////////////////////////////////
// None

////////////////////////////////////////////////////////////////////////////////
// Design                                                                     //
////////////////////////////////////////////////////////////////////////////////
///// Instance /////////////////////////////////////////////////////////////////
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ps_pwok (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPS_PWOK), .o(ps_pwok_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_p5v_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iP5V_PG), .o(p5v_pg_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_p3v3_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iP3V3_PG), .o(p3v3_pg_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_p1v8_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iP1V8_PG), .o(p1v8_pg_deb));

    assign p5v_en_hi = (ps_pwok_deb);
    assign p5v_en_lo = (~(ps_pwok_deb));
    assign p5v_en_force = 1'b0;  // No Force condition
    assign p3v3_en_hi = (p5v_pg_deb);
    assign p3v3_en_lo = (~(p5v_pg_deb));
    assign p3v3_en_force = 1'b0;  // No Force condition
    assign p1v8_en_hi = (p3v3_pg_deb);
    assign p1v8_en_lo = (~(p3v3_pg_deb));
    assign p1v8_en_force = 1'b0;  // No Force condition
    assign p1v1_hub_en_hi = (p1v8_pg_deb);
    assign p1v1_hub_en_lo = (~(p1v8_pg_deb));
    assign p1v1_hub_en_force = 1'b0;  // No Force condition

    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_p5v_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(p5v_en_hi), .iLo(p5v_en_lo), .iForce(p5v_en_force), .o(p5v_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_p3v3_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(p3v3_en_hi), .iLo(p3v3_en_lo), .iForce(p3v3_en_force), .o(p3v3_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_p1v8_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(p1v8_en_hi), .iLo(p1v8_en_lo), .iForce(p1v8_en_force), .o(p1v8_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_p1v1_hub_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(p1v1_hub_en_hi), .iLo(p1v1_hub_en_lo), .iForce(p1v1_hub_en_force), .o(p1v1_hub_en));
///// Always Block /////////////////////////////////////////////////////////////
    // None

///// Continuous Assignment ////////////////////////////////////////////////////
    assign oP5V_EN = p5v_en;
    assign oP3V3_EN = p3v3_en;
    assign oP1V8_EN = p1v8_en;
    assign oP1V1_HUB_EN = p1v1_hub_en;

endmodule //mg204_pseq
`endif  //MG204_PSEQ_V