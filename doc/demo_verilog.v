`timescale 1ns / 1ps
////////////////////////////////////////////////////////////////////////////////
// Module                : demo_verilog                                       //
// Author                : pwrseq_gen (Auto-generated)                        //
// Date Simulation Tested:                                                    //
//                                                                            //
// Function Description  :                                                    //
//   Power Sequence. output: oXXX, input: iXXX.                               //
//   iHi from depends_on (output: out, input: in). iLo default 1'b0.          //
// Change Log            :                                                    //
//   Auto-generated.                                                          //
////////////////////////////////////////////////////////////////////////////////
`ifndef DEMO_VERILOG_V
`define DEMO_VERILOG_V

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
module demo_verilog
////////////////////////////////////////////////////////////////////////////////
// Parameter Declare                                                          //
////////////////////////////////////////////////////////////////////////////////
//#(
//    No parameters
//)
////////////////////////////////////////////////////////////////////////////////
// Input/Output Port Declare                                                  //
////////////////////////////////////////////////////////////////////////////////
(
    input  iRst,
    input  iClk_Core,
    input  iPulse_1us, iPulse_1ms, iPulse_2ms, iPulse_32ms,
    input  iEKEY,
    input  iPRIM_VR_EN,
    output oPCH_P0V85A_EN,
    input  iPCH_P0V85A_PG,
    output oPCH_P1V25A_EN,
    input  iPCH_P1V25A_PG,
    output oPCH_P1V8A_EN,
    input  iPCH_P1V8A_PG,
    output oPCH_P3V3A_EN,
    input  iPCH_P3V3A_PG,
    output oPVNNAON_EN,
    input  iPVNNAON_PG,
    output oPVCCIO_EN,
    input  iPVCCIO_PG,
    output oPVCC1V8_EN,
    input  iPVCC1V8_PG,
    output oRSMRST_N,
    input  iSLPS5_N,
    input  iSLPS4_N,
    input  iSLPS3_N,
    output oPSU_EN,
    input  iPSU_PG,
    output oPVCCDD2_EN,
    input  iPVCCDD2_PG,
    output oIMVP_VR_EN,
    input  iIMVP_VR_PG,
    output oPCH_PWROK,
    input  iPLTRST_N
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
wire ekey_deb;
wire prim_vr_en_deb;
wire pch_p0v85a_en;
wire pch_p0v85a_pg_deb;
wire pch_p1v25a_en;
wire pch_p1v25a_pg_deb;
wire pch_p1v8a_en;
wire pch_p1v8a_pg_deb;
wire pch_p3v3a_en;
wire pch_p3v3a_pg_deb;
wire pvnnaon_en;
wire pvnnaon_pg_deb;
wire pvccio_en;
wire pvccio_pg_deb;
wire pvcc1v8_en;
wire pvcc1v8_pg_deb;
wire rsmrst_n;
wire slps5_n_deb;
wire slps4_n_deb;
wire slps3_n_deb;
wire psu_en;
wire psu_pg_deb;
wire pvccdd2_en;
wire pvccdd2_pg_deb;
wire imvp_vr_en;
wire imvp_vr_pg_deb;
wire pch_pwrok;
wire pltrst_n_deb;

// Condition signals (iHi, iLo, iForce) for PSEQCELL
wire pch_p0v85a_en_hi, pch_p0v85a_en_lo, pch_p0v85a_en_force;
wire pch_p1v25a_en_hi, pch_p1v25a_en_lo, pch_p1v25a_en_force;
wire pch_p1v8a_en_hi , pch_p1v8a_en_lo , pch_p1v8a_en_force ;
wire pch_p3v3a_en_hi , pch_p3v3a_en_lo , pch_p3v3a_en_force ;
wire pvnnaon_en_hi   , pvnnaon_en_lo   , pvnnaon_en_force   ;
wire pvccio_en_hi    , pvccio_en_lo    , pvccio_en_force    ;
wire pvcc1v8_en_hi   , pvcc1v8_en_lo   , pvcc1v8_en_force   ;
wire rsmrst_n_hi     , rsmrst_n_lo     , rsmrst_n_force     ;
wire psu_en_hi       , psu_en_lo       , psu_en_force       ;
wire pvccdd2_en_hi   , pvccdd2_en_lo   , pvccdd2_en_force   ;
wire imvp_vr_en_hi   , imvp_vr_en_lo   , imvp_vr_en_force   ;
wire pch_pwrok_hi    , pch_pwrok_lo    , pch_pwrok_force    ;

////////////////////////////////////////////////////////////////////////////////
// Task Define                                                                //
////////////////////////////////////////////////////////////////////////////////
// None

////////////////////////////////////////////////////////////////////////////////
// Design                                                                     //
////////////////////////////////////////////////////////////////////////////////
///// Instance /////////////////////////////////////////////////////////////////
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ekey          (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iEKEY         ), .o(ekey_deb         ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_prim_vr_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPRIM_VR_EN   ), .o(prim_vr_en_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p0v85a_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P0V85A_PG), .o(pch_p0v85a_pg_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p1v25a_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P1V25A_PG), .o(pch_p1v25a_pg_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p1v8a_pg  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P1V8A_PG ), .o(pch_p1v8a_pg_deb ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p3v3a_pg  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P3V3A_PG ), .o(pch_p3v3a_pg_deb ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvnnaon_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVNNAON_PG   ), .o(pvnnaon_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvccio_pg     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVCCIO_PG    ), .o(pvccio_pg_deb    ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvcc1v8_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVCC1V8_PG   ), .o(pvcc1v8_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slps5_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPS5_N      ), .o(slps5_n_deb      ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slps4_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPS4_N      ), .o(slps4_n_deb      ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slps3_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPS3_N      ), .o(slps3_n_deb      ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_psu_pg        (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPSU_PG       ), .o(psu_pg_deb       ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvccdd2_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVCCDD2_PG   ), .o(pvccdd2_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_imvp_vr_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iIMVP_VR_PG   ), .o(imvp_vr_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pltrst_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPLTRST_N     ), .o(pltrst_n_deb     ));

    assign pch_p0v85a_en_hi = (ekey_deb & prim_vr_en_deb);
    assign pch_p0v85a_en_lo = ((~rsmrst_n));
    assign pch_p0v85a_en_force = 1'b0;  // No Force condition

    assign pch_p1v25a_en_hi = (pch_p0v85a_pg_deb & pvnnaon_pg_deb);
    assign pch_p1v25a_en_lo = (pch_p0v85a_en_lo & (~pch_p0v85a_pg_deb));
    assign pch_p1v25a_en_force = 1'b0;  // No Force condition

    assign pch_p1v8a_en_hi = (pch_p1v25a_pg_deb & pvccio_pg_deb);
    assign pch_p1v8a_en_lo = (pch_p1v25a_en_lo & (~pch_p1v25a_pg_deb));
    assign pch_p1v8a_en_force = 1'b0;  // No Force condition

    assign pch_p3v3a_en_hi = (pch_p1v8a_pg_deb & pvcc1v8_pg_deb);
    assign pch_p3v3a_en_lo = (pch_p1v8a_en_lo & (~pch_p1v8a_pg_deb));
    assign pch_p3v3a_en_force = 1'b0;  // No Force condition

    assign pvnnaon_en_hi = (pch_p0v85a_en_hi);
    assign pvnnaon_en_lo = ((~rsmrst_n));
    assign pvnnaon_en_force = 1'b0;  // No Force condition

    assign pvccio_en_hi = (pch_p1v25a_en_hi);
    assign pvccio_en_lo = (pvnnaon_en_lo & (~pvnnaon_pg_deb));
    assign pvccio_en_force = 1'b0;  // No Force condition

    assign pvcc1v8_en_hi = (pch_p1v8a_en_hi);
    assign pvcc1v8_en_lo = (pvccio_en_lo & (~pvccio_pg_deb));
    assign pvcc1v8_en_force = 1'b0;  // No Force condition

    assign rsmrst_n_hi = (pch_p0v85a_en_hi & pch_p0v85a_pg_deb & pvnnaon_pg_deb & pch_p1v25a_pg_deb & pvccio_pg_deb & pch_p1v8a_pg_deb & pvcc1v8_pg_deb & pch_p3v3a_pg_deb);
    assign rsmrst_n_lo = !(prim_vr_en_deb & pch_p0v85a_pg_deb & pvnnaon_pg_deb & pch_p1v25a_pg_deb & pvccio_pg_deb & pch_p1v8a_pg_deb & pvcc1v8_pg_deb & pch_p3v3a_pg_deb);
    assign rsmrst_n_force = 1'b0;  // No Force condition

    assign psu_en_hi = (rsmrst_n & slps3_n_deb);
    assign psu_en_lo = ((~slps3_n_deb) & (~imvp_vr_pg_deb));
    assign psu_en_force = (pvccdd2_en_force);

    assign pvccdd2_en_hi = (rsmrst_n & slps4_n_deb);
    assign pvccdd2_en_lo = ((~pch_pwrok));
    assign pvccdd2_en_force = (pch_pwrok_force & (~imvp_vr_en) & (~slps4_n_deb));

    assign imvp_vr_en_hi = (rsmrst_n & pvccdd2_pg_deb & slps3_n_deb & psu_pg_deb);
    assign imvp_vr_en_lo = ((~slps3_n_deb));
    assign imvp_vr_en_force = 1'b0;  // No Force condition

    assign pch_pwrok_hi = (imvp_vr_en_hi & imvp_vr_pg_deb);
    assign pch_pwrok_lo = ((~slps3_n_deb));
    assign pch_pwrok_force = 1'b0;  // No Force condition

    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(5), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pch_p0v85a_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_2ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p0v85a_en_hi), .iLo(pch_p0v85a_en_lo), .iForce(pch_p0v85a_en_force), .o(pch_p0v85a_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pch_p1v25a_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p1v25a_en_hi), .iLo(pch_p1v25a_en_lo), .iForce(pch_p1v25a_en_force), .o(pch_p1v25a_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pch_p1v8a_en  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p1v8a_en_hi ), .iLo(pch_p1v8a_en_lo ), .iForce(pch_p1v8a_en_force ), .o(pch_p1v8a_en ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pch_p3v3a_en  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p3v3a_en_hi ), .iLo(pch_p3v3a_en_lo ), .iForce(pch_p3v3a_en_force ), .o(pch_p3v3a_en ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pvnnaon_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvnnaon_en_hi   ), .iLo(pvnnaon_en_lo   ), .iForce(pvnnaon_en_force   ), .o(pvnnaon_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pvccio_en     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvccio_en_hi    ), .iLo(pvccio_en_lo    ), .iForce(pvccio_en_force    ), .o(pvccio_en    ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pvcc1v8_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvcc1v8_en_hi   ), .iLo(pvcc1v8_en_lo   ), .iForce(pvcc1v8_en_force   ), .o(pvcc1v8_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(3), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_rsmrst_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(rsmrst_n_hi     ), .iLo(rsmrst_n_lo     ), .iForce(rsmrst_n_force     ), .o(rsmrst_n     ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(4), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_psu_en        (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_32ms), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(psu_en_hi       ), .iLo(psu_en_lo       ), .iForce(psu_en_force       ), .o(psu_en       ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pvccdd2_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvccdd2_en_hi   ), .iLo(pvccdd2_en_lo   ), .iForce(pvccdd2_en_force   ), .o(pvccdd2_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(2), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_imvp_vr_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(imvp_vr_en_hi   ), .iLo(imvp_vr_en_lo   ), .iForce(imvp_vr_en_force   ), .o(imvp_vr_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(3), .CYCLE_LO(4), .CYCLE_FORCE(2), .RECOVER(2'b11), .FORCE(0), .CYCLE_SYNC(0), .OD(0)) u_pch_pwrok     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1ms ), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_pwrok_hi    ), .iLo(pch_pwrok_lo    ), .iForce(pch_pwrok_force    ), .o(pch_pwrok    ));
///// Always Block /////////////////////////////////////////////////////////////
    // None

///// Continuous Assignment ////////////////////////////////////////////////////
    assign oPCH_P0V85A_EN = pch_p0v85a_en;
    assign oPCH_P1V25A_EN = pch_p1v25a_en;
    assign oPCH_P1V8A_EN  = pch_p1v8a_en;
    assign oPCH_P3V3A_EN  = pch_p3v3a_en;
    assign oPVNNAON_EN    = pvnnaon_en;
    assign oPVCCIO_EN     = pvccio_en;
    assign oPVCC1V8_EN    = pvcc1v8_en;
    assign oRSMRST_N      = rsmrst_n;
    assign oPSU_EN        = psu_en;
    assign oPVCCDD2_EN    = pvccdd2_en;
    assign oIMVP_VR_EN    = imvp_vr_en;
    assign oPCH_PWROK     = pch_pwrok;

endmodule //demo_verilog
`endif  //DEMO_VERILOG_V