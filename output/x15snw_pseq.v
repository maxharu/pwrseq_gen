`timescale 1ns / 1ps
////////////////////////////////////////////////////////////////////////////////
// Module                : x15snw_pseq                                        //
// Author                : pwrseq_gen (Auto-generated)                        //
// Date Simulation Tested:                                                    //
//                                                                            //
// Function Description  :                                                    //
//   Power Sequence. output: oXXX, input: iXXX.                               //
//   iHi from depends_on (output: out, input: in). iLo default 1'b0.          //
// Change Log            :                                                    //
//   Auto-generated.                                                           //
////////////////////////////////////////////////////////////////////////////////
`ifndef X15SNW_PSEQ_V
`define X15SNW_PSEQ_V

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
module x15snw_pseq
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
    input  iPulse_1us, iPulse_1ms,
    input  iEKEY,
    input  iSLPSUS_N,
    input  iBMC_SRST_N,
    input  iBMC_ON_CTRL_N,
    output oPCH_P0V85A_EN,
    input  iPCH_P0V85A_PG,
    output oPCH_P1V25A_EN,
    input  iPCH_P1V25A_PG,
    output oPCH_P1V8A_EN,
    input  iPCH_P1V8A_PG,
    input  iP3V3_A_PG,
    output oPVNNAON_EN,
    input  iPVNNAON_PG,
    output oPVCCIO_EN,
    input  iPVCCIO_PG,
    output oP1V8PROC_EN,
    input  iP1V8PROC_PG,
    output oRSMRST_N,
    input  iSLPS3_N,
    input  iSLPS4_N,
    input  iSLPS5_N,
    output oPS_EN,
    input  iPS_PG,
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
wire slpsus_n_deb;
wire bmc_srst_n_deb;
wire bmc_on_ctrl_n_deb;
wire pch_p0v85a_en;
wire pch_p0v85a_pg_deb;
wire pch_p1v25a_en;
wire pch_p1v25a_pg_deb;
wire pch_p1v8a_en;
wire pch_p1v8a_pg_deb;
wire p3v3_a_pg_deb;
wire pvnnaon_en;
wire pvnnaon_pg_deb;
wire pvccio_en;
wire pvccio_pg_deb;
wire p1v8proc_en;
wire p1v8proc_pg_deb;
wire rsmrst_n;
wire slps3_n_deb;
wire slps4_n_deb;
wire slps5_n_deb;
wire ps_en;
wire ps_pg_deb;
wire pvccdd2_en;
wire pvccdd2_pg_deb;
wire imvp_vr_en;
wire imvp_vr_pg_deb;
wire pch_pwrok;
wire pltrst_n_deb;

// Condition signals (iHi, iLo, iForce) for PSEQCELL
wire pch_p0v85a_en_hi, pch_p0v85a_en_lo, pch_p0v85a_en_force;
wire pch_p1v25a_en_hi, pch_p1v25a_en_lo, pch_p1v25a_en_force;
wire pch_p1v8a_en_hi, pch_p1v8a_en_lo, pch_p1v8a_en_force;
wire pvnnaon_en_hi, pvnnaon_en_lo, pvnnaon_en_force;
wire pvccio_en_hi, pvccio_en_lo, pvccio_en_force;
wire p1v8proc_en_hi, p1v8proc_en_lo, p1v8proc_en_force;
wire rsmrst_n_hi, rsmrst_n_lo, rsmrst_n_force;
wire ps_en_hi, ps_en_lo, ps_en_force;
wire pvccdd2_en_hi, pvccdd2_en_lo, pvccdd2_en_force;
wire imvp_vr_en_hi, imvp_vr_en_lo, imvp_vr_en_force;
wire pch_pwrok_hi, pch_pwrok_lo, pch_pwrok_force;

////////////////////////////////////////////////////////////////////////////////
// Task Define                                                                //
////////////////////////////////////////////////////////////////////////////////
// None

////////////////////////////////////////////////////////////////////////////////
// Design                                                                     //
////////////////////////////////////////////////////////////////////////////////
///// Instance /////////////////////////////////////////////////////////////////
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ekey          (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iEKEY         ), .o(ekey_deb         ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slpsus_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPSUS_N     ), .o(slpsus_n_deb     ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_bmc_srst_n    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iBMC_SRST_N   ), .o(bmc_srst_n_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_bmc_on_ctrl_n (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iBMC_ON_CTRL_N), .o(bmc_on_ctrl_n_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p0v85a_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P0V85A_PG), .o(pch_p0v85a_pg_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p1v25a_pg (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P1V25A_PG), .o(pch_p1v25a_pg_deb));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pch_p1v8a_pg  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPCH_P1V8A_PG ), .o(pch_p1v8a_pg_deb ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_p3v3_a_pg     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iP3V3_A_PG    ), .o(p3v3_a_pg_deb    ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvnnaon_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVNNAON_PG   ), .o(pvnnaon_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvccio_pg     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVCCIO_PG    ), .o(pvccio_pg_deb    ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_p1v8proc_pg   (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iP1V8PROC_PG  ), .o(p1v8proc_pg_deb  ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slps3_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPS3_N      ), .o(slps3_n_deb      ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slps4_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPS4_N      ), .o(slps4_n_deb      ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slps5_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iSLPS5_N      ), .o(slps5_n_deb      ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ps_pg         (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPS_PG        ), .o(ps_pg_deb        ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pvccdd2_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPVCCDD2_PG   ), .o(pvccdd2_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_imvp_vr_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iIMVP_VR_PG   ), .o(imvp_vr_pg_deb   ));
    DEB #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pltrst_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPLTRST_N     ), .o(pltrst_n_deb     ));

    assign pch_p0v85a_en_hi = (ekey_deb & slpsus_n_deb);
    assign pch_p0v85a_en_lo = ((~slpsus_n_deb));
    assign pch_p0v85a_en_force = 1'b0;  // No Force condition

    assign pch_p1v25a_en_hi = (pch_p0v85a_pg_deb & pch_p0v85a_en_hi);
    assign pch_p1v25a_en_lo = (pch_p0v85a_en_lo & (~pch_p0v85a_pg_deb));
    assign pch_p1v25a_en_force = 1'b0;  // No Force condition

    assign pch_p1v8a_en_hi = (pch_p1v25a_pg_deb & pch_p1v25a_en_hi);
    assign pch_p1v8a_en_lo = (pch_p1v25a_en_lo & (~pch_p1v25a_pg_deb));
    assign pch_p1v8a_en_force = 1'b0;  // No Force condition

    assign pvnnaon_en_hi = (pch_p0v85a_en_hi);
    assign pvnnaon_en_lo = ((~slpsus_n_deb));
    assign pvnnaon_en_force = 1'b0;  // No Force condition

    assign pvccio_en_hi = (pch_p1v25a_en);
    assign pvccio_en_lo = (pvnnaon_en_lo & (~pvnnaon_pg_deb));
    assign pvccio_en_force = 1'b0;  // No Force condition

    assign p1v8proc_en_hi = (pch_p1v8a_en_hi);
    assign p1v8proc_en_lo = (pvccio_en_lo & (~pvccio_pg_deb));
    assign p1v8proc_en_force = 1'b0;  // No Force condition

    assign rsmrst_n_hi = (p3v3_a_pg_deb & bmc_srst_n_deb);
    assign rsmrst_n_lo = ((~slpsus_n_deb));
    assign rsmrst_n_force = 1'b0;  // No Force condition

    assign ps_en_hi = (slps3_n_deb & rsmrst_n);
    assign ps_en_lo = ((~slps3_n_deb) & (~imvp_vr_pg_deb));
    assign ps_en_force = (pvccdd2_en_force);

    assign pvccdd2_en_hi = (ps_pg_deb & ps_en_hi);
    assign pvccdd2_en_lo = ((~pch_pwrok));
    assign pvccdd2_en_force = (pch_pwrok_force & (~imvp_vr_en) & (~slps4_n_deb));

    assign imvp_vr_en_hi = (pvccdd2_pg_deb);
    assign imvp_vr_en_lo = ((~slps3_n_deb));
    assign imvp_vr_en_force = 1'b0;  // No Force condition

    assign pch_pwrok_hi = (pvccdd2_pg_deb & imvp_vr_pg_deb & ps_pg_deb & slps3_n_deb & (~bmc_on_ctrl_n_deb));
    assign pch_pwrok_lo = ((~slps3_n_deb));
    assign pch_pwrok_force = ((~ps_pg_deb) & slps3_n_deb);

    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pch_p0v85a_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p0v85a_en_hi), .iLo(pch_p0v85a_en_lo), .iForce(pch_p0v85a_en_force), .o(pch_p0v85a_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pch_p1v25a_en (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p1v25a_en_hi), .iLo(pch_p1v25a_en_lo), .iForce(pch_p1v25a_en_force), .o(pch_p1v25a_en));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pch_p1v8a_en  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_p1v8a_en_hi ), .iLo(pch_p1v8a_en_lo ), .iForce(pch_p1v8a_en_force ), .o(pch_p1v8a_en ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pvnnaon_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvnnaon_en_hi   ), .iLo(pvnnaon_en_lo   ), .iForce(pvnnaon_en_force   ), .o(pvnnaon_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pvccio_en     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvccio_en_hi    ), .iLo(pvccio_en_lo    ), .iForce(pvccio_en_force    ), .o(pvccio_en    ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_p1v8proc_en   (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(p1v8proc_en_hi  ), .iLo(p1v8proc_en_lo  ), .iForce(p1v8proc_en_force  ), .o(p1v8proc_en  ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_rsmrst_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(rsmrst_n_hi     ), .iLo(rsmrst_n_lo     ), .iForce(rsmrst_n_force     ), .o(rsmrst_n     ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_ps_en         (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(ps_en_hi        ), .iLo(ps_en_lo        ), .iForce(ps_en_force        ), .o(ps_en        ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pvccdd2_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pvccdd2_en_hi   ), .iLo(pvccdd2_en_lo   ), .iForce(pvccdd2_en_force   ), .o(pvccdd2_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_imvp_vr_en    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(imvp_vr_en_hi   ), .iLo(imvp_vr_en_lo   ), .iForce(imvp_vr_en_force   ), .o(imvp_vr_en   ));
    PSEQCELL #(.INIT(0), .WIDTH(1), .CYCLE_HI(8), .CYCLE_LO(4), .CYCLE_FORCE(2), .OD(0)) u_pch_pwrok     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Hi(iPulse_1us), .iPulse_Lo(iPulse_1us), .iPulse_Force(iPulse_1us), .iHi(pch_pwrok_hi    ), .iLo(pch_pwrok_lo    ), .iForce(pch_pwrok_force    ), .o(pch_pwrok    ));
///// Always Block /////////////////////////////////////////////////////////////
    // None

///// Continuous Assignment ////////////////////////////////////////////////////
    assign oPCH_P0V85A_EN = pch_p0v85a_en;
    assign oPCH_P1V25A_EN = pch_p1v25a_en;
    assign oPCH_P1V8A_EN  = pch_p1v8a_en;
    assign oPVNNAON_EN    = pvnnaon_en;
    assign oPVCCIO_EN     = pvccio_en;
    assign oP1V8PROC_EN   = p1v8proc_en;
    assign oRSMRST_N      = rsmrst_n;
    assign oPS_EN         = ps_en;
    assign oPVCCDD2_EN    = pvccdd2_en;
    assign oIMVP_VR_EN    = imvp_vr_en;
    assign oPCH_PWROK     = pch_pwrok;

endmodule //x15snw_pseq
`endif  //X15SNW_PSEQ_V