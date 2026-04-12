`timescale 1ns / 1ps
////////////////////////////////////////////////////////////////////////////////
// Module                : x15_pseq                                           //
// Author                : Haru Chen                                          //
// Date Simulation Tested:                                                    //
//                                                                            //
// Function Description  :                                                    //
//   Design Flow                                                              //
//   1. Design Normal On/Off Condition                                        //
//   2. Design Reset Event                                                    //
//        a. Reset Event Pulse                                                //
//        b. Reset Event Latch (Enable, Clr)                                  //
//   3. Design Reset Condition                                                //
//   4. Fine tune the timing                                                  //
//   Note:                                                                    //
//     One power rail, one EN and one PG                                      //
//     If power rail with double EN, {2{EN}} => {EN1, EN0}                    //
//     If power rail with double PG, PG <= PG0 & PG1                          //
// Change Log            :                                                    //
//   2025-11-13                                                               //
//     Add PDG T74 behavior                                                   //
//   2025-11-12                                                               //
//     Add DDR_PCAMP_A1                                                       //
//   2025-07-09                                                               //
//     Initial design.                                                        //
////////////////////////////////////////////////////////////////////////////////
`ifndef X15_PSEQ_V
`define X15_PSEQ_V

////////////////////////////////////////////////////////////////////////////////
// Define                                                                     //
////////////////////////////////////////////////////////////////////////////////
/*
//G3->S5
-T3(50m)-> VCCVNN[L] -> VCCFA_EHV[L] -> AUX_PWRGOOD[L] -T5(100u)-> GLOBAL_RESET_N[L]
//S5->G3
GLOBAL_RESET_N[L] -> AUX_PWRGOOD[L] -> VCCFA_EHV[L](VCCVNN[L])

//S5->S0
*S5_N -> *S4_N -> *S3_N -> PSON_N -> PS_PWROK ->
VCCVNN[NL] -> VCCFA_EHV[NL]-> AUX_PWRGOOD[NL]   -T6(1us)-> GLOBAL_RESET_N[NL] -> //Multi-Socket Only
VCCD_HV    -> VCCANA       -> VCCA_HV -> VCCINF -> VCCIN -> 
S0_PWR_OK  -> *REFCLK_READY->CPUPWRGOOD   -> *PLTRST_SYNC -> RESET_N
                                          -> PERST_N:M2   -> PERST_N:M1
//S0->S5
*PLTRST_SYNC -> RESET_N -> *S3_N -> *S4_N -> *S5_N
                                          -> CPUPWRGOOD -T45(1m)-> S0_PWR_OK -> VCCIN(VCCINF, VCCA_HV, VCCANA, VCCD_HV) -T51(100u)-> GLOBAL_RESET_N[NL] -> AUX_PWRGOOD[NL] -> VCCFA_EHV[NL](VCCVNN[NL]) -> PSON_N
                                                                -> PERST_N:M2
                        -> PERST_N:M1
//MEM On
VCCD_HV -> PCAMP[0:n] -> DDR_PWROKxx -> *DDR_RESET_N -> DRAM_RESET_N
//MEM Off
*S4_N -> DDR_PWROKxx -> PCAMP -> DRAM_RESET_N
                     -> *DDR_RESET_N

//S5 Global Reset
GLB_RST_WARN_N[L]:L -> GLOBAL_RESET_N[L]:L -> GLOBAL_RESET_N[L]:H -> GLB_RST_WARN_N[L]:H
//S0 Global Reset
GLB_RST_WARN_N[L]:L -> RESET_N -> CPUPWRGOOD -> S0_PWR_OK -> DDR_PWROKxx -> VCCIN(VCCINF, VCCA_HV, VCCANA, VCCD_HV) -------------------| 
                               -> PERST_N:M1                             -> DDR_RESET_N -> DRAM_RESET_N                                | 
                                             -> PERST_N:M2               -> PCAMP                                                      |  
                                                                         -> GLOBAL_RESET_N[L] -> GLOBAL_RESET_N[NL] -> AUX_PWRGOOD[NL] -> VCCFA_EHV[NL](VCCVNN[NL]) -> PSON_N??
                                                                                              -> S3_N(S4_N, S5_N)
//Asyn Global Reset
PLAT GR Source      -> RESET_N -> CPUPWRGOOD -> S0_PWR_OK -> DDR_PWROKxx -> VCCIN(VCCINF, VCCA_HV, VCCANA, VCCD_HV) -------------------| 
                               -> PERST_N:M1                             -> DDR_RESET_N -> DRAM_RESET_N                                |
                                             -> PERST_N:M2               -> PCAMP                                                      |
                                                                         -> GLOBAL_RESET_N[L] -> GLOBAL_RESET_N[NL] -> AUX_PWRGOOD[NL] -> VCCFA_EHV[NL](VCCVNN[NL]??) -> PSON_N??
                                                                                                  -> S3_N(S4_N, S5_N) -> PSON_N
//PSU AC Loss (No ADR)
PS_PWROK            -> RESET_N -> CPUPWRGOOD -> S0_PWR_OK -> DDR_PWROKxx -> VCCIN(VCCINF, VCCA_HV, VCCANA, VCCD_HV) -------------------|
                               -> PERST_N:M1                             -> DDR_RESET_N -> DRAM_RESET_N                                |
                                             -> PERST_N:M2               -> PCAMP                                                      |
                                                                         -> GLOBAL_RESET_N[L] -> GLOBAL_RESET_N[NL] -> AUX_PWRGOOD[NL] -> VCCFA_EHV[NL](VCCVNN[NL]) -> PSON_N
                                                                                              -> S3_N(S4_N, S5_N)
//Thermtrip_N, MBVR_Failure
Thermtrip_N(MBVR)   -> RESET_N -> CPUPWRGOOD -> S0_PWR_OK -> DDR_PWROKxx -> PCAMP -> DRAM_RESET_N
                               -> PERST_N:M1                             -> GLOBAL_RESET_N -> AUX_PWRGOOD -> VCCIN(VCCINF, VCCA_HV, VCCANA, VCCD_HV) -> 
                                             -> PERST_N:M2                                                -> VCCFA_EHV(VCCVNN)
                                                                                                          -> PSON_N
*/
////////////////////////////////////////////////////////////////////////////////
// Library Include                                                            //
////////////////////////////////////////////////////////////////////////////////
//`include "./INC/_INC.v"

////////////////////////////////////////////////////////////////////////////////
// Module Declare                                                             //
////////////////////////////////////////////////////////////////////////////////
module x15_pseq
////////////////////////////////////////////////////////////////////////////////
// Parameter Declare                                                          //
////////////////////////////////////////////////////////////////////////////////
#(
    parameter NUM_CPU      = 2,
    parameter PERST_METHOD = 0,     //0: RESET_N, 1: CPUPWRGOOD
    parameter NUM_CPU_MEM  = 8 
)
////////////////////////////////////////////////////////////////////////////////
// Input/Output Port Declare                                                  //
////////////////////////////////////////////////////////////////////////////////
(
    input  iRst, iClk_Core,
    input  iPulse_1us, iPulse_32us, iPulse_1ms, iPulse_16ms,
    //CTRL
    input  iNOCPU_TEST,
    input  [(NUM_CPU*2)-1:0]iPKG_ID,
    input  [(NUM_CPU*2)-1:0]iPROC_ID,
    
    input  [(NUM_CPU  )-1:0]iSKTOCC_N,
    input  [(NUM_CPU  )-1:0]iSINGLE_DIMM_CFG_I,     output [(NUM_CPU  )-1:0]oSINGLE_DIMM_CFG_O,
    output oSINGLE_DIMM_CFG_DONE,
    //SEQ
    //G3->Sx
    input  iVAUX_RDY,
    output [(NUM_CPU  )-1:0]oVCCVNN_EN,             input  [(NUM_CPU  )-1:0]iVCCVNN_PG,         //P1_PVNN_MAIN_EN_V33O,         P1_PVNN_MAIN_PG_V33I
    output [(NUM_CPU  )-1:0]oVCCFA_EHV_EN,          input  [(NUM_CPU  )-1:0]iVCCFA_EHV_PG,      //P1_PVCCFA_EN_V33O,            P1_VCCFAEHV_PG_V33I
    output [(NUM_CPU  )-1:0]oAUX_PWRGOOD,                                                       //PWRGD_PLT_AUX_CPU1_V18o
    output [(NUM_CPU  )-1:0]oGLOBAL_RESET_N,                                                    //CPU1_GLOBAL_RESET_N_V18O
    
    //Sx->Sx
    input  iSLP_S4_N,
    input  iSLP_S3_N,
    output oPSU_EN,                                 input  iPS_PWROK,
    output [(NUM_CPU  )-1:0]oVCCD_HV_EN,            input  [(NUM_CPU  )-1:0]iVCCD_HV_PG,        //P1_PVCCD_HV_EN_V33O,          P1_PVCCD0_HV_PG_V33I & P1_PVCCD1_HV_PG_V33I
    output [(NUM_CPU  )-1:0]oVCCANA_EN,             input  [(NUM_CPU  )-1:0]iVCCANA_PG,         //P1_PVCCANA_EN_V33O,           P1_VCCANA0_PG_V33I   & P1_VCCANA1_PG_V33I
    output [(NUM_CPU  )-1:0]oVCCA_HV_EN,            input  [(NUM_CPU  )-1:0]iVCCA_HV_PG,        //P1_PVCCA_HV_EN_V33O,          P1_VCCA_HV_PG_V33I
    output [(NUM_CPU  )-1:0]oVCCINF_EN,             input  [(NUM_CPU  )-1:0]iVCCINF_PG,         //P1_VCCINF_EN_V33O,            P1_VCCINF_PG_V33I
    output [(NUM_CPU  )-1:0]oVCCIN_EN,              input  [(NUM_CPU  )-1:0]iVCCIN_PG,          //P1_VCCIN_EN_V33O,             P1_VCCIN_EHV0_PG_V33I & P1_VCCIN_EHV1_PG_V33I
    
    output [(NUM_CPU  )-1:0]oS0_PWR_OK,             input  [(NUM_CPU  )-1:0]iREFCLK_READY,      //CPU1_S0_PWROK_OD,             CPU1_REFCLK_READY_V18I
    output [(NUM_CPU  )-1:0]oCPUPWRGOOD,            input  iPLTRST_SYNC_N,                      //PWRGD_CPU1_OD                 CPU1_PLTRST_SYNC_N
    output [(NUM_CPU  )-1:0]oRESET_N,                                                           //RESET_CPU1_N_R_OD
    //MEM
    //inout  [(NUM_CPU  )-1:0]ioDDR_PCAMP_A1,                                                   //CPU1_PLD_MEM_A1_PWRGD, For Single DIMM mode
    output [(NUM_CPU  )-1:0]oDDR_PCAMP_A1_O,        input [(NUM_CPU  )-1:0]iDDR_PCAMP_A1_I,
    //inout  [(NUM_CPU*NUM_CPU_MEM)-1:0]ioDDR_PCAMP,                                            //CPU1_PLD_MEM_XX_PWRGD * 8
    output [(NUM_CPU*NUM_CPU_MEM)-1:0]oDDR_PCAMP_O, input [(NUM_CPU*NUM_CPU_MEM)-1:0]iDDR_PCAMP_I,
    output [(NUM_CPU*NUM_CPU_MEM)-1:0]oDDR_PWROK,                                               //PLD_CPU1_MEM_XX_PWRGD_OD * 8
    input  [(NUM_CPU*NUM_CPU_MEM)-1:0]iDDR_RESET_N,                                             //CPU1_DDR_XX_RST_N * 8
    output [(NUM_CPU*NUM_CPU_MEM)-1:0]oDRAM_RESET_N,                                            //M_XX_CPU1_FPGA_RESET_N * 8

    //Misc
    output oPERST_N,
    output [(NUM_CPU  )-1:0]oCPU_PRSNT,
    
    input  iGLB_RST_WARN_N,
    input  [(NUM_CPU  )-1:0]iTHERMTRIP_N,
    
    //ADR
    input  iADR_EN,
    input  iADR_EVENT,
    input  iADR_COMPLETE,
    output oADR_TRIGGER_N,
    
    //DEBUG
    output oEVENT_THERMTRIP,
    output oEVENT_MBVR_FAIL,
    output oEVENT_DDR5_PFAIL,
    output oEVENT_AC_LOSS,

    input  iEVENT_THERMTRIP_CLR,
    input  iEVENT_MBVR_FAIL_CLR,
    input  iEVENT_DDR5_PFAIL_CLR,
    input  iEVENT_AC_LOSS_CLR,

    output [(NUM_CPU*4)-1:0]oTRACING
);

////////////////////////////////////////////////////////////////////////////////
// Function Include                                                           //
////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////
// Local Parameter Declare                                                    //
////////////////////////////////////////////////////////////////////////////////
localparam PERST_METHOD_RESET_N    = 0;
localparam PERST_METHOD_CPUPWRGOOD = 1;

////////////////////////////////////////////////////////////////////////////////
// Internal Signal Declare                                                    //
////////////////////////////////////////////////////////////////////////////////
integer i;
genvar gv_cpu, gv_mem;
//Flow Control
wire multi_socket;

//Input Debounce
wire vaux_rdy_deb;
wire [(NUM_CPU  )-1:0]vccvnn_pg_deb, vccfa_ehv_pg_deb;

wire slp_s3_n_deb, slp_s4_n_deb;
wire ps_pwrok_deb;
wire [(NUM_CPU  )-1:0]vccd_hv_pg_deb, vccana_pg_deb, vcca_hv_pg_deb, vccinf_pg_deb, vccin_pg_deb;
wire [(NUM_CPU  )-1:0]refclk_ready_deb;
wire pltrst_sync_n_deb;
wire [(NUM_CPU  )-1:0]perst_n_src_deb;

wire [(NUM_CPU*NUM_CPU_MEM)-1:0]ddr_reset_n_deb;
wire [(NUM_CPU*NUM_CPU_MEM)-1:0]ddr_pcamp_i_deb, ddr_pcamp_o;
wire [(NUM_CPU            )-1:0]ddr_pcamp_a1_i_deb, ddr_pcamp_a1_o;
wire [(NUM_CPU            )-1:0]ddr_pcamp_ch0_i_hi_deb, ddr_pcamp_ch0_i_lo_deb;

wire glb_rst_warn_n_deb;
wire [(NUM_CPU  )-1:0]thermtrip_n_deb;

wire [(NUM_CPU  )-1:0]all_aux_vr_on   =  (vccvnn_pg_deb &  vccfa_ehv_pg_deb);
wire [(NUM_CPU  )-1:0]all_aux_vr_off  = ~(vccvnn_pg_deb |  vccfa_ehv_pg_deb);
wire [(NUM_CPU  )-1:0]all_aux_vr_fail =  (oVCCVNN_EN    & ~vccvnn_pg_deb   ) | 
                                         (oVCCFA_EHV_EN & ~vccfa_ehv_pg_deb);

wire [(NUM_CPU  )-1:0]all_prim_vr_on  =  (vccd_hv_pg_deb & vccana_pg_deb & vcca_hv_pg_deb & vccinf_pg_deb & vccin_pg_deb);
wire [(NUM_CPU  )-1:0]all_prim_vr_off = ~(vccd_hv_pg_deb | vccana_pg_deb | vcca_hv_pg_deb | vccinf_pg_deb | vccin_pg_deb);
wire [(NUM_CPU  )-1:0]all_prim_vr_fail_wo_vccd_hv= (oVCCANA_EN  & ~vccana_pg_deb ) | 
                                                   (oVCCA_HV_EN & ~vcca_hv_pg_deb) | 
                                                   (oVCCINF_EN  & ~vccinf_pg_deb ) | 
                                                   (oVCCIN_EN   & ~vccin_pg_deb  );

//Output Condition
//VCCVNN
wire [NUM_CPU-1:0]vccvnn_en_hi, vccvnn_en_lo, vccvnn_en_force;
//VCCFA_EHV_EN
wire [NUM_CPU-1:0]vccfa_ehv_en_hi, vccfa_ehv_en_lo, vccfa_ehv_en_force;
//AUX_PWRGOOD
wire [NUM_CPU-1:0]aux_pwrgood_hi, aux_pwrgood_lo, aux_pwrgood_force;
//GLOBAL_RESET_N
wire [NUM_CPU-1:0]global_reset_n_hi, global_reset_n_lo, global_reset_n_force;
//PSU
wire psu_en_hi, psu_en_lo, psu_en_force;
//VCCD_HV
wire [NUM_CPU-1:0]vccd_hv_en_hi, vccd_hv_en_lo, vccd_hv_en_force;
//VCCANA
wire [NUM_CPU-1:0]vccana_en_hi, vccana_en_lo, vccana_en_force;
//VCCA_HV
wire [NUM_CPU-1:0]vcca_hv_en_hi, vcca_hv_en_lo, vcca_hv_en_force;
//VCCINF
wire [NUM_CPU-1:0]vccinf_en_hi, vccinf_en_lo, vccinf_en_force;
//VCCIN
wire [NUM_CPU-1:0]vccin_en_hi, vccin_en_lo, vccin_en_force;
//S0_PWR_OK
wire [NUM_CPU-1:0]s0_pwr_ok_hi, s0_pwr_ok_lo, s0_pwr_ok_force;
//CPUPWRGOOD
wire [NUM_CPU-1:0]cpupwrgood_hi, cpupwrgood_lo, cpupwrgood_force;
//RESET_N
wire [NUM_CPU-1:0]reset_n_hi, reset_n_lo, reset_n_force;
//DDR_PCAMP
wire [NUM_CPU-1:0]ddr_pcamp_a1_hi, ddr_pcamp_a1_lo, ddr_pcamp_a1_force;
wire [(NUM_CPU*NUM_CPU_MEM)-1:0]ddr_pcamp_hi, ddr_pcamp_lo, ddr_pcamp_force;
//DDR_PWROK
wire [(NUM_CPU*NUM_CPU_MEM)-1:0]ddr_pwrok_hi, ddr_pwrok_lo, ddr_pwrok_force;
//DRAM_RESET_N
wire [(NUM_CPU*NUM_CPU_MEM)-1:0]dram_reset_n_hi, dram_reset_n_lo, dram_reset_n_force;

//EVENT
wire event_s5_global_reset, posedge_s5_global_reset;
wire event_s0_global_reset, posedge_s0_global_reset;
wire event_ac_loss_no_adr,  posedge_ac_loss_no_adr ;
wire event_thermtrip,       posedge_thermtrip      ;
wire event_mbvr_fail,       posedge_mbvr_fail      ;
wire event_ddr_pfail_case1, posedge_ddr_pfail_case1; 
wire event_ddr_pfail_case2, posedge_ddr_pfail_case2;

wire rst_s0_global_reset, rst_ac_loss;
wire rst_thermtrip_n, rst_mbvr_fail;

wire [(NUM_CPU*NUM_CPU_MEM)-1:0]event_ddr_pfail_case1_p;
wire [NUM_CPU              -1:0]event_ddr_pfail_case2_p;
wire rst_ddr5_pfail_case1, rst_ddr5_pfail_case2;
wire rst_ddr5_pfail = rst_ddr5_pfail_case1 | rst_ddr5_pfail_case2;

wire deb_t74;
wire [NUM_CPU-1:0]deb_t71;

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
    //G3
    DEB #(.WIDTH(1                  ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vaux_rdy      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVAUX_RDY            ), .o(vaux_rdy_deb      ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vccvnn        (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCVNN_PG           ), .o(vccvnn_pg_deb     ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vccfa_ehv     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCFA_EHV_PG        ), .o(vccfa_ehv_pg_deb  ));
    //Sx
    DEB #(.WIDTH(1                  ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slp_s3_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iNOCPU_TEST|iSLP_S3_N), .o(slp_s3_n_deb      ));
    DEB #(.WIDTH(1                  ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_slp_s4_n      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iNOCPU_TEST|iSLP_S4_N), .o(slp_s4_n_deb      ));
    DEB #(.WIDTH(1                  ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ps_pwrok      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPS_PWROK            ), .o(ps_pwrok_deb      ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vccd_hv_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCD_HV_PG          ), .o(vccd_hv_pg_deb    ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vccana_pg     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCANA_PG           ), .o(vccana_pg_deb     ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vcca_hv_pg    (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCA_HV_PG          ), .o(vcca_hv_pg_deb    ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vccinf_pg     (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCINF_PG           ), .o(vccinf_pg_deb     ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_vccin_pg      (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iVCCIN_PG            ), .o(vccin_pg_deb      ));
    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_refclk_ready  (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iREFCLK_READY        ), .o(refclk_ready_deb  ));
    DEB #(.WIDTH(1                  ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_pltrst_sync_n (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iPLTRST_SYNC_N       ), .o(pltrst_sync_n_deb ));
    //MEM
    DEB #(.WIDTH(NUM_CPU*NUM_CPU_MEM), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ddr_reset_n   (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_1us), .i(iDDR_RESET_N         ), .o(ddr_reset_n_deb   ));

    DEB #(.WIDTH(NUM_CPU*NUM_CPU_MEM), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ddr_ddr_pcamp (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(1'b1),       .i(iDDR_PCAMP_I         ), .o(ddr_pcamp_i_deb   ));
    //GPIO_DEB #(.WIDTH(NUM_CPU*NUM_CPU_MEM), .INIT({NUM_CPU*NUM_CPU_MEM{1'b0}}), .CYCLE_SYNC(2), .CYCLE_DEB_HI(3), .CYCLE_DEB_LO(3), .OPEN({NUM_CPU*NUM_CPU_MEM{1'b1}})) u_deb_ddr_pcamp (
    //    .iRst(iRst),                        .iClk_Core(iClk_Core),              .iPulse_Deb(1'b1),
    //    .iOE({NUM_CPU*NUM_CPU_MEM{1'b1}}),  .iIE({NUM_CPU*NUM_CPU_MEM{1'b1}}),  .iOPE({NUM_CPU*NUM_CPU_MEM{1'b1}}),
    //    .iDO(ddr_pcamp_o),                  .oDI(ddr_pcamp_i_deb),              .ioIO(ioDDR_PCAMP)
    //);

    DEB #(.WIDTH(NUM_CPU            ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_ddr_ddr_pcamp_a1(.iRst(iRst),.iClk_Core(iClk_Core),.iPulse_Sample(1'b1),       .i(iDDR_PCAMP_A1_I      ), .o(ddr_pcamp_a1_i_deb));
    //GPIO_DEB #(.WIDTH(NUM_CPU            ), .INIT({NUM_CPU            {1'b0}}), .CYCLE_SYNC(2), .CYCLE_DEB_HI(3), .CYCLE_DEB_LO(3), .OPEN({NUM_CPU            {1'b1}})) u_deb_ddr_a1_pcamp (
    //    .iRst(iRst),                        .iClk_Core(iClk_Core),              .iPulse_Deb(1'b1),
    //    .iOE({NUM_CPU             {1'b1}}), .iIE({NUM_CPU             {1'b1}}), .iOPE({NUM_CPU            {1'b1}}),
    //    .iDO(ddr_pcamp_a1_o),               .oDI(ddr_pcamp_a1_i_deb),           .ioIO(ioDDR_PCAMP_A1)
    //);

    //MISC
    DEB #(.WIDTH(1        ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(3), .CYCLE_LO(3)) u_deb_glb_rst_warn_n(.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(1'b1), .i(iGLB_RST_WARN_N), .o(glb_rst_warn_n_deb));
    DEB #(.WIDTH(NUM_CPU  ), .INIT(1), .CYCLE_SYNC(2), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_thermtrip_n   (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(1'b1), .i(iTHERMTRIP_N   ), .o(thermtrip_n_deb   ));
    DEB #(.WIDTH(NUM_CPU  ), .INIT(0), .CYCLE_SYNC(0), .CYCLE_HI(2), .CYCLE_LO(2)) u_deb_perst_n       (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(1'b1), .i((PERST_METHOD==PERST_METHOD_RESET_N) ? oRESET_N : oAUX_PWRGOOD), .o(perst_n_src_deb));

    //Timing
    DEB #(.WIDTH(1        ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(15),.CYCLE_LO(2)) u_deb_t74           (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_16ms), .i(rst_ddr5_pfail_case1 & (~|oRESET_N)), .o(deb_t74));
    DEB #(.WIDTH(NUM_CPU  ), .INIT(0), .CYCLE_SYNC(2), .CYCLE_HI(3), .CYCLE_LO(0)) u_deb_t71           (.iRst(iRst), .iClk_Core(iClk_Core), .iPulse_Sample(iPulse_32us), .i({NUM_CPU{rst_s0_global_reset|rst_ac_loss|rst_thermtrip_n|rst_mbvr_fail|rst_ddr5_pfail_case1}} & ~oCPUPWRGOOD), .o(deb_t71));

    //G3->Sx
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(5), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vccvnn           (iRst,  iClk_Core,  iPulse_16ms,iPulse_1us, iPulse_32us,vccvnn_en_hi,       vccvnn_en_lo,       vccvnn_en_force,        oVCCVNN_EN      );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(2), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vccfa_ehv        (iRst,  iClk_Core,  iPulse_1ms, iPulse_1us, iPulse_32us,vccfa_ehv_en_hi,    vccfa_ehv_en_lo,    vccfa_ehv_en_force,     oVCCFA_EHV_EN   );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(2), .CYCLE_LO(2), .CYCLE_FORCE(0), .OD(0), .FORCE(0)) u_qseq_aux_pwrgood      (iRst,  iClk_Core,  iPulse_1ms, iPulse_1us, iPulse_1us, aux_pwrgood_hi,     aux_pwrgood_lo,     aux_pwrgood_force,      oAUX_PWRGOOD    );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(2), .CYCLE_LO(5), .CYCLE_FORCE(0), .OD(0), .FORCE(0)) u_qseq_global_reset_n   (iRst,  iClk_Core,  iPulse_1ms, iPulse_32us,iPulse_1us, global_reset_n_hi,  global_reset_n_lo,  global_reset_n_force,   oGLOBAL_RESET_N );
    //Sx->Sx
    PSEQCELL #(.INIT(0), .WIDTH(1        ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_psu              (iRst,  iClk_Core,  iPulse_1ms, iPulse_1ms, iPulse_32us,psu_en_hi,          psu_en_lo,          psu_en_force,           oPSU_EN         );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vccd_hv          (iRst,  iClk_Core,  iPulse_1ms, iPulse_32us,iPulse_32us,vccd_hv_en_hi,      vccd_hv_en_lo,      vccd_hv_en_force,       oVCCD_HV_EN     );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vccana           (iRst,  iClk_Core,  iPulse_1ms, iPulse_32us,iPulse_32us,vccana_en_hi,       vccana_en_lo,       vccana_en_force,        oVCCANA_EN      );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vcca_hv          (iRst,  iClk_Core,  iPulse_1ms, iPulse_32us,iPulse_32us,vcca_hv_en_hi,      vcca_hv_en_lo,      vcca_hv_en_force,       oVCCA_HV_EN     );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vccinf           (iRst,  iClk_Core,  iPulse_1ms, iPulse_32us,iPulse_32us,vccinf_en_hi,       vccinf_en_lo,       vccinf_en_force,        oVCCINF_EN      );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_vccin            (iRst,  iClk_Core,  iPulse_1ms, iPulse_32us,iPulse_32us,vccin_en_hi,        vccin_en_lo,        vccin_en_force,         oVCCIN_EN       );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(2), .CYCLE_FORCE(2), .OD(0), .FORCE(0)) u_qseq_s0_pwr_ok        (iRst,  iClk_Core,  iPulse_16ms,iPulse_1ms, iPulse_1us, s0_pwr_ok_hi,       s0_pwr_ok_lo,       s0_pwr_ok_force,        oS0_PWR_OK      );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(3), .CYCLE_FORCE(0), .OD(0), .FORCE(0)) u_qseq_cpupwrgood       (iRst,  iClk_Core,  iPulse_1us, 1'b1,       1'b1,       cpupwrgood_hi,      cpupwrgood_lo,      cpupwrgood_force,       oCPUPWRGOOD     );
    PSEQCELL #(.INIT(0), .WIDTH(NUM_CPU  ), .CYCLE_HI(3), .CYCLE_LO(1), .CYCLE_FORCE(0), .OD(0), .FORCE(0)) u_qseq_reset_n          (iRst,  iClk_Core,  iPulse_1ms, 1'b1,       1'b1,       reset_n_hi,         reset_n_lo,         reset_n_force,          oRESET_N        );
    //MEM
    PSEQCELL #(.INIT(0),.WIDTH(NUM_CPU            ),.CYCLE_HI(3),.CYCLE_LO(1),.CYCLE_FORCE(1),.OD(0),.FORCE(0)) u_qseq_ddr_a1_pcamp (iRst,  iClk_Core,  1'b1,       1'b1,       1'b1,       ddr_pcamp_a1_hi,    ddr_pcamp_a1_lo,    ddr_pcamp_a1_force,     oDDR_PCAMP_A1_O );
    PSEQCELL #(.INIT(0),.WIDTH(NUM_CPU*NUM_CPU_MEM),.CYCLE_HI(3),.CYCLE_LO(1),.CYCLE_FORCE(1),.OD(0),.FORCE(0)) u_qseq_ddr_pcamp    (iRst,  iClk_Core,  1'b1,       1'b1,       1'b1,       ddr_pcamp_hi,       ddr_pcamp_lo,       ddr_pcamp_force,        oDDR_PCAMP_O    );
    PSEQCELL #(.INIT(0),.WIDTH(NUM_CPU*NUM_CPU_MEM),.CYCLE_HI(3),.CYCLE_LO(1),.CYCLE_FORCE(1),.OD(0),.FORCE(0)) u_qseq_ddr_pwrok    (iRst,  iClk_Core,  1'b1,       1'b1,       1'b1,       ddr_pwrok_hi,       ddr_pwrok_lo,       ddr_pwrok_force,        oDDR_PWROK      );
    PSEQCELL #(.INIT(0),.WIDTH(NUM_CPU*NUM_CPU_MEM),.CYCLE_HI(3),.CYCLE_LO(1),.CYCLE_FORCE(1),.OD(0),.FORCE(0)) u_qseq_dram_reset_n (iRst,  iClk_Core,  1'b1,       1'b1,       1'b1,       dram_reset_n_hi,    dram_reset_n_lo,    dram_reset_n_force,     oDRAM_RESET_N   );

    //EVENT
    assign event_s5_global_reset = ~pltrst_sync_n_deb & ~glb_rst_warn_n_deb;
    assign event_s0_global_reset =  pltrst_sync_n_deb & ~glb_rst_warn_n_deb;
    assign event_ac_loss_no_adr  =  pltrst_sync_n_deb & ~iADR_EN            & ~ps_pwrok_deb & oPSU_EN;
    assign event_thermtrip       =  pltrst_sync_n_deb & |(oCPU_PRSNT        & ~thermtrip_n_deb);
    assign event_mbvr_fail       =  pltrst_sync_n_deb & |(oCPU_PRSNT        & (all_aux_vr_fail | all_prim_vr_fail_wo_vccd_hv));
    assign event_ddr_pfail_case1 = |event_ddr_pfail_case1_p;
    assign event_ddr_pfail_case2 = |event_ddr_pfail_case2_p;

    PSEQRST #(.WIDTH(6)) u_rst (
        .iRst(iRst | (~oPSU_EN & ~ps_pwrok_deb)),  .iClk_Core(iClk_Core),
        .iEn({6{pltrst_sync_n_deb}}),
        .iEvent({
            event_s0_global_reset,      
            event_ac_loss_no_adr,
            event_thermtrip,            
            event_mbvr_fail,            
            event_ddr_pfail_case1,      
            event_ddr_pfail_case2
        }), 
        .oEventPosedge({
            posedge_s0_global_reset,    
            posedge_ac_loss_no_adr,   
            posedge_thermtrip,          
            posedge_mbvr_fail,          
            posedge_ddr_pfail_case1,    
            posedge_ddr_pfail_case2
        }),
        .oEventRst({
            rst_s0_global_reset,        
            rst_ac_loss,                
            rst_thermtrip_n,            
            rst_mbvr_fail,              
            rst_ddr5_pfail_case1,       
            rst_ddr5_pfail_case2
        })
    );
    
    wire rst_s5_global_reset_l;
    EGDET #(.WIDTH(1), .INIT(0), .CYCLE_SYNC(0), .TYPE(2'b10)) u_event_edge (
        .iRst(iRst),                    .iClk_Core(iClk_Core), 
        .i(event_s5_global_reset),      .o(posedge_s5_global_reset)
    );
    TRG #(.WIDTH(1), .POLAR(1), .CYCLE_DELAY(3), .CYCLE_TRIGGER(6), .CYCLE_RECOVER(0)) u_glbrst_l_s5_rst (
        .iRst(iRst),                    .iClk_Core(iClk_Core),
        .iPulse_Delay(iPulse_1ms),      .iPulse_Trigger(iPulse_1ms),.iPulse_Recover(iPulse_1ms),
        .i(posedge_s5_global_reset),    .o(rst_s5_global_reset_l)
    );
    
    wire rst_s0_global_reset_l, rst_global_reset_l_ac_loss;
    TRG #(.WIDTH(2), .POLAR(1), .CYCLE_DELAY(2), .CYCLE_TRIGGER(6), .CYCLE_RECOVER(6)) u_glbrst_l_s0_rst (
        .iRst(iRst),                    .iClk_Core(iClk_Core),
        .iPulse_Delay(iPulse_1us),      .iPulse_Trigger(iPulse_1ms),.iPulse_Recover(iPulse_1ms),
        .i({
            event_s0_global_reset & ~(|oDDR_PWROK),
            event_ac_loss_no_adr  & ~(|oDDR_PWROK)
        }),
        .o({
            rst_s0_global_reset_l,
            rst_global_reset_l_ac_loss
        })
    );

    //ADR
    x15_pseq_adr #(.CYCLE_DEB(3)) u_adr (
        .iRst(iRst),            .iClk_Core(iClk_Core),  .iPulse_Deb(iPulse_1us),
        .iEn(iADR_EN),      
        .iPS_PWROK(iPS_PWROK),                          .iSLPS3_N(iSLP_S3_N),
        .iEVENT(iADR_EVENT),                            .iCOMPLETE(iADR_COMPLETE),
        .oTRIGGER_N(oADR_TRIGGER_N)
    );
    
generate
for (gv_cpu=0; gv_cpu<NUM_CPU; gv_cpu=gv_cpu+1) begin
    pseq_peakHolder #(.NUM_IN(15), .VALUE_CLR((gv_cpu==0) ? 4 : 0)) u_peak_holder (
        .iRst(iRst),                .iClk_Core(iClk_Core),
        .iIN({
            iPLTRST_SYNC_N,         iREFCLK_READY[gv_cpu],  oS0_PWR_OK[gv_cpu],     oCPUPWRGOOD[gv_cpu],
            iVCCIN_PG[gv_cpu],      iVCCINF_PG[gv_cpu],     iVCCA_HV_PG[gv_cpu],    
            iVCCANA_PG[gv_cpu],     iVCCD_HV_PG[gv_cpu],    iPS_PWROK,              iSLP_S3_N,              
            oGLOBAL_RESET_N[gv_cpu],oAUX_PWRGOOD[gv_cpu],   iVCCFA_EHV_PG[gv_cpu],  iVCCVNN_PG[gv_cpu]
        }),
        .oOUT(oTRACING[gv_cpu*4+:4]),   .oDone()
    );
end
endgenerate
///// Always Block /////////////////////////////////////////////////////////////
    //DEBUG
    reg rEvent_Thermtrip, rEvent_MbvrFail;
    reg rEvent_DdrPFail_case1, rEvent_DdrPFail_case2;
    reg rEvent_AC_Loss;
    always @(posedge iClk_Core) begin: EVENT
        if (iRst) begin
            rEvent_Thermtrip<= #1 0;
            rEvent_MbvrFail <= #1 0;
            rEvent_AC_Loss  <= #1 0;
            rEvent_DdrPFail_case1 <= #1 0;
            rEvent_DdrPFail_case2 <= #1 0;
        end else begin
            if (iEVENT_THERMTRIP_CLR & rEvent_Thermtrip)rEvent_Thermtrip <= #1 1'b0;
            else if (posedge_thermtrip)                 rEvent_Thermtrip <= #1 1'b1;
            
            if (iEVENT_MBVR_FAIL_CLR & rEvent_MbvrFail) rEvent_MbvrFail <= #1 1'b0;
            else if (posedge_mbvr_fail)                 rEvent_MbvrFail <= #1 1'b1;
            
            if (iEVENT_AC_LOSS_CLR & rEvent_AC_Loss)    rEvent_AC_Loss <= #1 1'b0;
            else if (posedge_ac_loss_no_adr)            rEvent_AC_Loss <= #1 1'b1;
            
            if (iEVENT_DDR5_PFAIL_CLR & rEvent_DdrPFail_case1) rEvent_DdrPFail_case1 <= #1 1'b0;
            else if (posedge_ddr_pfail_case1)                  rEvent_DdrPFail_case1 <= #1 1'b1;
            
            if (iEVENT_DDR5_PFAIL_CLR & rEvent_DdrPFail_case2) rEvent_DdrPFail_case2 <= #1 1'b0;
            else if (posedge_ddr_pfail_case2)                  rEvent_DdrPFail_case2 <= #1 1'b1;
        end
    end
    assign oEVENT_THERMTRIP  = rEvent_Thermtrip;
    assign oEVENT_MBVR_FAIL  = rEvent_MbvrFail;
    assign oEVENT_AC_LOSS    = rEvent_AC_Loss;
    assign oEVENT_DDR5_PFAIL = rEvent_DdrPFail_case1 | rEvent_DdrPFail_case2;
    
    //SINGLE_DIMM_CFG
    reg [(NUM_CPU)-1:0]rSingleDimmCfg;
    reg rSingleDimmCfgDone;
    reg [1:0]rCntSingleDimmCfg;
    always @(posedge iClk_Core) begin: SINGLE_DIMM_CFG
        if (iRst) begin
            rSingleDimmCfg     <= #1 {NUM_CPU{1'b1}};
            rSingleDimmCfgDone <= #1 1'b0;
            rCntSingleDimmCfg  <= #1 0;
        end else begin
            if (!rSingleDimmCfgDone) begin
                if (iPulse_16ms) begin
                    rCntSingleDimmCfg <= #1 rCntSingleDimmCfg + 1;
                    if (&rCntSingleDimmCfg) begin
                        rSingleDimmCfgDone <= #1 1'b1;
                        for (i=0; i<NUM_CPU; i=i+1) begin
                            rSingleDimmCfg[i] <= #1 &ddr_pcamp_i_deb[(i*NUM_CPU_MEM)+:NUM_CPU_MEM] && !ddr_pcamp_a1_i_deb[i];
                        end
                    end
                end
            end else begin
                rCntSingleDimmCfg <= #1 0;
            end
        end
    end
    assign oSINGLE_DIMM_CFG_O    = rSingleDimmCfg;
    assign oSINGLE_DIMM_CFG_DONE = rSingleDimmCfgDone;
///// Continuous Assignment ////////////////////////////////////////////////////
generate
for (gv_cpu=0; gv_cpu<NUM_CPU; gv_cpu=gv_cpu+1) begin
    if (gv_cpu==0) assign oCPU_PRSNT[gv_cpu] = iNOCPU_TEST || (                 (~iSKTOCC_N[gv_cpu] && (iPROC_ID[2*gv_cpu+:2]==2'b00        ) && (iPKG_ID[2*gv_cpu+:2]==2'b00       )));
    else           assign oCPU_PRSNT[gv_cpu] = iNOCPU_TEST || (oCPU_PRSNT[0] && (~iSKTOCC_N[gv_cpu] && (iPROC_ID[2*gv_cpu+:2]==iPROC_ID[1:0]) && (iPKG_ID[2*gv_cpu+:2]==iPKG_ID[1:0])));
    
    if (gv_cpu==0) begin
        assign vccvnn_en_hi        [gv_cpu] = oCPU_PRSNT[gv_cpu] & vaux_rdy_deb;
        assign vccvnn_en_lo        [gv_cpu] = aux_pwrgood_lo[gv_cpu] & ~oAUX_PWRGOOD[gv_cpu];
        assign vccvnn_en_force     [gv_cpu] = (rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oAUX_PWRGOOD[gv_cpu];

        assign vccfa_ehv_en_hi     [gv_cpu] = vccvnn_en_hi[gv_cpu] & vccvnn_pg_deb[gv_cpu];
        assign vccfa_ehv_en_lo     [gv_cpu] = vccvnn_en_lo[gv_cpu];
        assign vccfa_ehv_en_force  [gv_cpu] = (rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oAUX_PWRGOOD[gv_cpu];

        assign aux_pwrgood_hi      [gv_cpu] = vccfa_ehv_en_hi[gv_cpu] & vccfa_ehv_pg_deb[gv_cpu];
        assign aux_pwrgood_lo      [gv_cpu] = global_reset_n_lo[gv_cpu] & ~oGLOBAL_RESET_N[gv_cpu];
        assign aux_pwrgood_force   [gv_cpu] = (rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oGLOBAL_RESET_N[gv_cpu];

        assign global_reset_n_hi   [gv_cpu] = aux_pwrgood_hi[gv_cpu] & oAUX_PWRGOOD[gv_cpu];
        assign global_reset_n_lo   [gv_cpu] = ~vaux_rdy_deb;
        assign global_reset_n_force[gv_cpu] = rst_s5_global_reset_l | rst_s0_global_reset_l | rst_global_reset_l_ac_loss | ((rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oS0_PWR_OK[gv_cpu] & (~|oDDR_PWROK[(gv_cpu*NUM_CPU_MEM)+:NUM_CPU_MEM]));
    end else begin
        assign vccvnn_en_hi        [gv_cpu] =  oCPU_PRSNT[gv_cpu] & slp_s3_n_deb & ps_pwrok_deb;
        assign vccvnn_en_lo        [gv_cpu] =  aux_pwrgood_lo[gv_cpu] & all_prim_vr_off[gv_cpu] & ~oAUX_PWRGOOD[gv_cpu];
        assign vccvnn_en_force     [gv_cpu] =  (rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oAUX_PWRGOOD[gv_cpu];
        
        assign vccfa_ehv_en_hi     [gv_cpu] =  vccvnn_en_hi[gv_cpu] & vccvnn_pg_deb[gv_cpu];
        assign vccfa_ehv_en_lo     [gv_cpu] =  vccvnn_en_lo[gv_cpu];
        assign vccfa_ehv_en_force  [gv_cpu] =  vccvnn_en_force[gv_cpu];
        
        assign aux_pwrgood_hi      [gv_cpu] =  vccfa_ehv_en_hi[gv_cpu] & vccfa_ehv_pg_deb[gv_cpu];
        assign aux_pwrgood_lo      [gv_cpu] =  global_reset_n_lo[gv_cpu] & ~oGLOBAL_RESET_N[gv_cpu];
        assign aux_pwrgood_force   [gv_cpu] =  (rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oGLOBAL_RESET_N[gv_cpu];
       
        assign global_reset_n_hi   [gv_cpu] =  aux_pwrgood_hi[gv_cpu] & oAUX_PWRGOOD[gv_cpu];
        assign global_reset_n_lo   [gv_cpu] =  s0_pwr_ok_lo[gv_cpu] & ~oS0_PWR_OK[gv_cpu] ;
        assign global_reset_n_force[gv_cpu] = ((rst_s0_global_reset | rst_ac_loss) & ~oGLOBAL_RESET_N[0]) | ((rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oS0_PWR_OK[gv_cpu] & (~|oDDR_PWROK[(gv_cpu*NUM_CPU_MEM)+:NUM_CPU_MEM]));
    end

    if (gv_cpu==0) begin
        assign psu_en_hi                  =  oGLOBAL_RESET_N[gv_cpu] & slp_s3_n_deb;
        assign psu_en_lo                  = (((NUM_CPU>=2) && multi_socket) ? &all_aux_vr_off[NUM_CPU-1:1] : all_prim_vr_off[gv_cpu]) & ~rst_ddr5_pfail_case1;
        assign psu_en_force               = (rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail_case2 | deb_t74) & ~oAUX_PWRGOOD[gv_cpu];
    end
    
        assign vccd_hv_en_hi     [gv_cpu] =  oCPU_PRSNT[gv_cpu] & slp_s3_n_deb & (((gv_cpu!=0) || multi_socket) ? &((~oCPU_PRSNT) | oGLOBAL_RESET_N) : ps_pwrok_deb);
        assign vccd_hv_en_lo     [gv_cpu] =  s0_pwr_ok_lo[gv_cpu] & ~oS0_PWR_OK[gv_cpu] ;
        assign vccd_hv_en_force  [gv_cpu] = ((rst_s0_global_reset | rst_ac_loss) & ~|oDDR_PWROK[gv_cpu*NUM_CPU_MEM+:NUM_CPU_MEM]) | ((rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail) & ~oAUX_PWRGOOD[gv_cpu]);

        assign vccana_en_hi      [gv_cpu] =  vccd_hv_en_hi[gv_cpu] & vccd_hv_pg_deb[gv_cpu];
        assign vccana_en_lo      [gv_cpu] =  vccd_hv_en_lo[gv_cpu];
        assign vccana_en_force   [gv_cpu] =  vccd_hv_en_force[gv_cpu];

        assign vcca_hv_en_hi     [gv_cpu] =  vccana_en_hi[gv_cpu] & vccana_pg_deb[gv_cpu];
        assign vcca_hv_en_lo     [gv_cpu] =  vccd_hv_en_lo[gv_cpu];
        assign vcca_hv_en_force  [gv_cpu] =  vccd_hv_en_force[gv_cpu];

        assign vccinf_en_hi      [gv_cpu] =  vcca_hv_en_hi[gv_cpu] & vcca_hv_pg_deb[gv_cpu];
        assign vccinf_en_lo      [gv_cpu] =  vccd_hv_en_lo[gv_cpu];
        assign vccinf_en_force   [gv_cpu] =  vccd_hv_en_force[gv_cpu];

        assign vccin_en_hi       [gv_cpu] =  vccinf_en_hi[gv_cpu] & vccinf_pg_deb[gv_cpu];
        assign vccin_en_lo       [gv_cpu] =  vccd_hv_en_lo[gv_cpu];
        assign vccin_en_force    [gv_cpu] =  vccd_hv_en_force[gv_cpu];

        assign s0_pwr_ok_hi      [gv_cpu] =  oCPU_PRSNT[gv_cpu] & slp_s3_n_deb & (&(~oCPU_PRSNT | (oGLOBAL_RESET_N & all_prim_vr_on)));                         //All CPUs asserted at the same time
        assign s0_pwr_ok_lo      [gv_cpu] =  cpupwrgood_lo[gv_cpu] & ~oCPUPWRGOOD[gv_cpu];
        assign s0_pwr_ok_force   [gv_cpu] =  deb_t71[gv_cpu] | (rst_ddr5_pfail_case2 & ~oCPUPWRGOOD[gv_cpu]);

        assign cpupwrgood_hi     [gv_cpu] =  oCPU_PRSNT[gv_cpu] & slp_s3_n_deb & (&(~oCPU_PRSNT | (oS0_PWR_OK & refclk_ready_deb)));                            //All CPUs asserted at the same time
        assign cpupwrgood_lo     [gv_cpu] =  reset_n_lo[gv_cpu] & ~oRESET_N[gv_cpu] & ~slp_s4_n_deb ;
        assign cpupwrgood_force  [gv_cpu] =  reset_n_force[gv_cpu] & ~oRESET_N[gv_cpu];

        assign reset_n_hi        [gv_cpu] =  oCPU_PRSNT[gv_cpu] & slp_s3_n_deb & (&(~oCPU_PRSNT | oCPUPWRGOOD)) & pltrst_sync_n_deb;                            //All CPUs asserted at the same time
        assign reset_n_lo        [gv_cpu] = ~pltrst_sync_n_deb;
        assign reset_n_force     [gv_cpu] =  rst_s0_global_reset | rst_ac_loss | rst_thermtrip_n | rst_mbvr_fail | rst_ddr5_pfail;
                
        //MEM
        assign ddr_pcamp_a1_hi   [gv_cpu] =  vccd_hv_pg_deb[gv_cpu];
        assign ddr_pcamp_a1_lo   [gv_cpu] =  ddr_pwrok_lo   [gv_cpu*NUM_CPU_MEM] & ~oDDR_PWROK[gv_cpu*NUM_CPU_MEM];
        assign ddr_pcamp_a1_force[gv_cpu] = (ddr_pwrok_force[gv_cpu*NUM_CPU_MEM] & ~oDDR_PWROK[gv_cpu*NUM_CPU_MEM]) | (rst_ddr5_pfail & ~oDRAM_RESET_N[gv_cpu]);

    for (gv_mem=0; gv_mem<NUM_CPU_MEM; gv_mem=gv_mem+1) begin
        assign ddr_pcamp_hi      [(gv_cpu*NUM_CPU_MEM)+gv_mem] = vccd_hv_pg_deb[gv_cpu];
        assign ddr_pcamp_lo      [(gv_cpu*NUM_CPU_MEM)+gv_mem] = ddr_pwrok_lo    [(gv_cpu*NUM_CPU_MEM)+gv_mem] & ~oDDR_PWROK[gv_cpu*NUM_CPU_MEM+gv_mem];
        assign ddr_pcamp_force   [(gv_cpu*NUM_CPU_MEM)+gv_mem] = (ddr_pwrok_force[(gv_cpu*NUM_CPU_MEM)+gv_mem] & ~oDDR_PWROK[gv_cpu*NUM_CPU_MEM+gv_mem]) | (rst_ddr5_pfail & ~oDRAM_RESET_N[gv_cpu*NUM_CPU_MEM+gv_mem]);

        assign ddr_pwrok_hi      [(gv_cpu*NUM_CPU_MEM)+gv_mem] = vccd_hv_pg_deb[gv_cpu] & ((gv_mem==0) ? ddr_pcamp_ch0_i_hi_deb[gv_cpu] : ddr_pcamp_i_deb[(gv_cpu*NUM_CPU_MEM)+gv_mem]);
        assign ddr_pwrok_lo      [(gv_cpu*NUM_CPU_MEM)+gv_mem] = reset_n_lo[gv_cpu] & ~oRESET_N[gv_cpu] & ~slp_s4_n_deb;
        assign ddr_pwrok_force   [(gv_cpu*NUM_CPU_MEM)+gv_mem] = ((rst_s0_global_reset | rst_ac_loss | rst_thermtrip_n | rst_mbvr_fail) & ~oS0_PWR_OK[gv_cpu]) | (rst_ddr5_pfail & ~oDRAM_RESET_N[gv_cpu*NUM_CPU_MEM+gv_mem]);

        assign dram_reset_n_hi   [(gv_cpu*NUM_CPU_MEM)+gv_mem] = ddr_reset_n_deb[(gv_cpu*NUM_CPU_MEM)+gv_mem] & oDDR_PWROK[(gv_cpu*NUM_CPU_MEM)+gv_mem];
        assign dram_reset_n_lo   [(gv_cpu*NUM_CPU_MEM)+gv_mem] = ddr_pcamp_lo[(gv_cpu*NUM_CPU_MEM)+gv_mem] & ~ddr_reset_n_deb[(gv_cpu*NUM_CPU_MEM)+gv_mem];
        assign dram_reset_n_force[(gv_cpu*NUM_CPU_MEM)+gv_mem] = (ddr_pwrok_force[(gv_cpu*NUM_CPU_MEM)+gv_mem] & ~ddr_reset_n_deb[gv_cpu*NUM_CPU_MEM+gv_mem]) | rst_ddr5_pfail;
    end
end

for (gv_cpu=0; gv_cpu<NUM_CPU; gv_cpu=gv_cpu+1) begin
    for (gv_mem=0; gv_mem<NUM_CPU_MEM; gv_mem=gv_mem+1) begin
        assign event_ddr_pfail_case1_p[(gv_cpu*NUM_CPU_MEM)+gv_mem] = oDDR_PWROK[(gv_cpu*NUM_CPU_MEM)+gv_mem] & ((gv_mem==0) ? ddr_pcamp_ch0_i_lo_deb[gv_cpu] : ~ddr_pcamp_i_deb[(gv_cpu*NUM_CPU_MEM)+gv_mem]);
    end
    assign event_ddr_pfail_case2_p[gv_cpu] = (|oDDR_PWROK[gv_cpu*NUM_CPU_MEM+:NUM_CPU_MEM]) & ~vccd_hv_pg_deb[gv_cpu];

    assign ddr_pcamp_ch0_i_hi_deb[gv_cpu] = iSINGLE_DIMM_CFG_I[gv_cpu] ?  ddr_pcamp_a1_i_deb[gv_cpu] : ( ddr_pcamp_a1_i_deb[gv_cpu] &  ddr_pcamp_i_deb[(gv_cpu*NUM_CPU_MEM)]);
    assign ddr_pcamp_ch0_i_lo_deb[gv_cpu] = iSINGLE_DIMM_CFG_I[gv_cpu] ? ~ddr_pcamp_a1_i_deb[gv_cpu] : (~ddr_pcamp_a1_i_deb[gv_cpu] & ~ddr_pcamp_i_deb[(gv_cpu*NUM_CPU_MEM)]);
end
endgenerate
    assign multi_socket  = (NUM_CPU >= 2) ? (|oCPU_PRSNT[NUM_CPU-1 : 1]) : 1'b0;
    assign oPERST_N      = &((~oCPU_PRSNT) | perst_n_src_deb);        //all sources with the CPU present are 1's

endmodule //x15_pseq
`endif  //X15_PSEQ_V
