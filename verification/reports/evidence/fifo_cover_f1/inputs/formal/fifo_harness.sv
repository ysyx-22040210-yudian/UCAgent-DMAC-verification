// Independent FIFO inputs with one reset sample and no fairness assumptions.
module fifo_harness #(parameter ADDR_W=32,LEN_W=32,FIFO_DEPTH=2)
    (input wire clk,rst_n,in_valid,out_ready,input wire [63:0] in_data);
wire in_ready,out_valid;
wire [63:0] out_data;
dmac_fifo #(.WIDTH(64),.DEPTH(FIFO_DEPTH)) dut
    (.clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_ready(in_ready),.in_data(in_data),
     .out_valid(out_valid),.out_ready(out_ready),.out_data(out_data),.f_count_out(),.f_head_out());
reg past_valid=0;
always @(posedge clk) begin
    past_valid<=1;
    if (!past_valid) M_CK_FIFO_RESET: assume(!rst_n);
end
endmodule
