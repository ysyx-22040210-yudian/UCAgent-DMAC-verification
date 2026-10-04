`timescale 1ns/1ns
// Synchronous, first-word-visible FIFO. DEPTH may be any positive integer.
module dmac_fifo #(
    parameter int unsigned WIDTH = 64,
    parameter int unsigned DEPTH = 2
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             in_valid,
    output logic             in_ready,
    input  logic [WIDTH-1:0] in_data,
    output logic             out_valid,
    input  logic             out_ready,
    output logic [WIDTH-1:0] out_data
`ifdef FORMAL
    , output wire [$clog2(DEPTH+1)-1:0] f_count_out
    , output wire [WIDTH-1:0] f_head_out
`endif
);
    localparam int unsigned PTR_W = (DEPTH > 1) ? $clog2(DEPTH) : 1;
    localparam int unsigned COUNT_W = $clog2(DEPTH + 1);
    logic [WIDTH-1:0] storage [0:DEPTH-1];
    logic [PTR_W-1:0] rd_ptr_q, wr_ptr_q;
    logic [COUNT_W-1:0] count_q;
    logic push, pop;

    assign out_valid = rst_n && (count_q != '0);
    assign out_data = out_valid ? storage[rd_ptr_q] : '0;
    assign pop = out_valid && out_ready;
    // Permit replacement of the oldest word when a full FIFO is popped.
    assign in_ready = rst_n && ((count_q < COUNT_W'(DEPTH)) || pop);
    assign push = in_valid && in_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_ptr_q <= '0;
            wr_ptr_q <= '0;
            count_q <= '0;
        end else begin
`ifndef SYNTHESIS
            assert (!(push && !pop && (count_q == COUNT_W'(DEPTH)))) else $fatal(1, "FIFO overflow");
            assert (!(pop && (count_q == '0))) else $fatal(1, "FIFO underflow");
`endif
            if (push) begin
                storage[wr_ptr_q] <= in_data;
                wr_ptr_q <= (wr_ptr_q == PTR_W'(DEPTH-1)) ? '0 : wr_ptr_q + 1'b1;
            end
            if (pop)
                rd_ptr_q <= (rd_ptr_q == PTR_W'(DEPTH-1)) ? '0 : rd_ptr_q + 1'b1;
            case ({push, pop})
                2'b10: count_q <= count_q + 1'b1;
                2'b01: count_q <= count_q - 1'b1;
                default: ;
            endcase
        end
    end

`ifndef SYNTHESIS
    initial begin
        assert (DEPTH >= 1) else $fatal(1, "FIFO DEPTH must be positive");
        assert (WIDTH >= 1) else $fatal(1, "FIFO WIDTH must be positive");
    end
`endif
`ifdef FORMAL
`include "fifo_monitor.svh"
`endif
endmodule
