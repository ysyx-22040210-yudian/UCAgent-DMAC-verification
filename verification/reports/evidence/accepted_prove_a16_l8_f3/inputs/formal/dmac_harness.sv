// Symbolic environment: a single initial reset sample; all later inputs free.
module dmac_harness #(
    parameter ADDR_W=32, LEN_W=32, FIFO_DEPTH=2
) (
    input wire clk, rst_n,
    input wire host_rd_req, host_wr_req,
    input wire [ADDR_W-1:0] host_rd_haddr, host_wr_haddr,
    input wire [LEN_W-1:0] host_rd_len, host_wr_len,
    input wire mem_rd_ready, mem_wr_ready,
    input wire [63:0] mem_rd_data,
    input wire dev_rd_req, dev_wr_req,
    input wire [15:0] dev_wr_data
);
wire host_rd_ack,host_wr_ack,host_rd_done,host_wr_done;
wire mem_rd_valid,mem_wr_valid,dev_rd_ack,dev_wr_ack;
wire [ADDR_W-1:0] mem_rd_addr,mem_wr_addr;
wire [63:0] mem_wr_data;
wire [15:0] dev_rd_data;
dmac #(.ADDR_W(ADDR_W),.LEN_W(LEN_W),.FIFO_DEPTH(FIFO_DEPTH)) dut (.*);
reg past_valid=0;
always @(posedge clk) begin
    past_valid<=1;
    if (!past_valid) M_CK_START_RESET: assume (!rst_n);
    if (past_valid) begin
        C_CK_RESET_ABORT_RD: cover (!rst_n && $past(mem_rd_valid && !mem_rd_ready));
        C_CK_RESET_ABORT_WR: cover (!rst_n && $past(mem_wr_valid && !mem_wr_ready));
    end
end
endmodule
