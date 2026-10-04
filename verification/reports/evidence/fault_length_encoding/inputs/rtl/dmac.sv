`timescale 1ns/1ns
// Independent memory-to-device and device-to-memory DMA channels.
// LEN encodes the number of 64-bit memory beats minus one.
module dmac #(
    parameter int unsigned ADDR_W = 32,
    parameter int unsigned LEN_W = 32,
    parameter int unsigned FIFO_DEPTH = 2
) (
    input  logic              clk,
    input  logic              rst_n,

    input  logic              host_rd_req,
    input  logic [ADDR_W-1:0] host_rd_haddr,
    input  logic [LEN_W-1:0]  host_rd_len,
    output logic              host_rd_ack,
    output logic              host_rd_done,
    input  logic              host_wr_req,
    input  logic [ADDR_W-1:0] host_wr_haddr,
    input  logic [LEN_W-1:0]  host_wr_len,
    output logic              host_wr_ack,
    output logic              host_wr_done,

    output logic              mem_rd_valid,
    input  logic              mem_rd_ready,
    output logic [ADDR_W-1:0] mem_rd_addr,
    input  logic [63:0]       mem_rd_data,
    output logic              mem_wr_valid,
    input  logic              mem_wr_ready,
    output logic [ADDR_W-1:0] mem_wr_addr,
    output logic [63:0]       mem_wr_data,

    input  logic              dev_rd_req,
    output logic              dev_rd_ack,
    output logic [15:0]       dev_rd_data,
    input  logic              dev_wr_req,
    output logic              dev_wr_ack,
    input  logic [15:0]       dev_wr_data
);
`ifdef FORMAL
    wire [$clog2(FIFO_DEPTH+1)-1:0] f_rd_count, f_wr_count;
    wire [63:0] f_rd_head, f_wr_head;
`endif
    logic rd_active_q, wr_active_q;
    logic [ADDR_W-1:0] rd_addr_q, wr_addr_q;
    // The extra bit represents 2**LEN_W for an all-ones length.
    logic [LEN_W:0] rd_fetch_left_q, rd_deliver_left_q;
    logic [LEN_W:0] wr_collect_left_q, wr_commit_left_q;
    logic [1:0] rd_lane_q, wr_lane_q;
    logic [63:0] wr_pack_q, wr_assembled;
    logic rd_fifo_ready, rd_fifo_valid, rd_fifo_pop;
    logic wr_fifo_ready, wr_fifo_valid, wr_fifo_push;
    logic [63:0] rd_fifo_data, wr_fifo_data;
    logic rd_mem_fire, rd_dev_fire, wr_mem_fire, wr_dev_fire;

    // One accepted command per direction. The done cycle is reserved for
    // reporting completion; a pending new command is accepted afterward.
    assign host_rd_ack = rst_n && host_rd_req && !rd_active_q && !host_rd_done;
    assign host_wr_ack = rst_n && host_wr_req && !wr_active_q && !host_wr_done;

    assign mem_rd_valid = rst_n && rd_active_q && (rd_fetch_left_q != '0) && rd_fifo_ready;
    assign mem_rd_addr = rd_addr_q;
    assign rd_mem_fire = mem_rd_valid && mem_rd_ready;
    assign dev_rd_ack = rst_n && rd_active_q && dev_rd_req && rd_fifo_valid;
    assign dev_rd_data = rd_fifo_data[16 * int'(rd_lane_q) +: 16];
    assign rd_dev_fire = dev_rd_req && dev_rd_ack;
    assign rd_fifo_pop = rd_dev_fire && (rd_lane_q == 2'd3);

    dmac_fifo #(.WIDTH(64), .DEPTH(FIFO_DEPTH)) u_rd_fifo (
        .clk(clk), .rst_n(rst_n),
        .in_valid(rd_mem_fire), .in_ready(rd_fifo_ready), .in_data(mem_rd_data),
        .out_valid(rd_fifo_valid), .out_ready(rd_fifo_pop), .out_data(rd_fifo_data)
`ifdef FORMAL
        , .f_count_out(f_rd_count), .f_head_out(f_rd_head)
`endif
    );

    // The pack register can collect the first three halfwords even when
    // the word FIFO is full. The fourth halfword requires FIFO space.
    assign dev_wr_ack = rst_n && wr_active_q && dev_wr_req &&
                        (wr_collect_left_q != '0) &&
                        ((wr_lane_q != 2'd3) || wr_fifo_ready);
    assign wr_dev_fire = dev_wr_req && dev_wr_ack;
    always_comb begin
        wr_assembled = wr_pack_q;
        wr_assembled[16 * int'(wr_lane_q) +: 16] = dev_wr_data;
    end
    assign wr_fifo_push = wr_dev_fire && (wr_lane_q == 2'd3);
    assign mem_wr_valid = rst_n && wr_active_q && wr_fifo_valid;
    assign mem_wr_addr = wr_addr_q;
    assign mem_wr_data = wr_fifo_data;
    assign wr_mem_fire = mem_wr_valid && mem_wr_ready;

    dmac_fifo #(.WIDTH(64), .DEPTH(FIFO_DEPTH)) u_wr_fifo (
        .clk(clk), .rst_n(rst_n),
        .in_valid(wr_fifo_push), .in_ready(wr_fifo_ready), .in_data(wr_assembled),
        .out_valid(wr_fifo_valid), .out_ready(wr_mem_fire), .out_data(wr_fifo_data)
`ifdef FORMAL
        , .f_count_out(f_wr_count), .f_head_out(f_wr_head)
`endif
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_active_q <= 1'b0;
            rd_addr_q <= '0;
            rd_fetch_left_q <= '0;
            rd_deliver_left_q <= '0;
            rd_lane_q <= '0;
            host_rd_done <= 1'b0;
        end else begin
            host_rd_done <= 1'b0;
`ifndef SYNTHESIS
            assert (!(rd_mem_fire && (rd_fetch_left_q == '0))) else $fatal(1, "Extra memory read");
            assert (!(host_rd_ack && rd_fifo_valid)) else $fatal(1, "Stale read data at new command");
`endif
            if (host_rd_ack) begin
                rd_active_q <= 1'b1;
                rd_addr_q <= host_rd_haddr;
                rd_fetch_left_q <= {1'b0, host_rd_len} + (LEN_W+1)'(0);
                rd_deliver_left_q <= {1'b0, host_rd_len} + (LEN_W+1)'(0);
                rd_lane_q <= '0;
            end else begin
                if (rd_mem_fire) begin
                    rd_addr_q <= rd_addr_q + ADDR_W'(8);
                    rd_fetch_left_q <= rd_fetch_left_q - 1'b1;
                end
                if (rd_dev_fire) begin
                    rd_lane_q <= rd_lane_q + 1'b1;
                    if (rd_lane_q == 2'd3) begin
                        rd_deliver_left_q <= rd_deliver_left_q - 1'b1;
                        if (rd_deliver_left_q == (LEN_W+1)'(1)) begin
                            rd_active_q <= 1'b0;
                            host_rd_done <= 1'b1;
                        end
                    end
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_active_q <= 1'b0;
            wr_addr_q <= '0;
            wr_collect_left_q <= '0;
            wr_commit_left_q <= '0;
            wr_lane_q <= '0;
            wr_pack_q <= '0;
            host_wr_done <= 1'b0;
        end else begin
            host_wr_done <= 1'b0;
`ifndef SYNTHESIS
            assert (!(wr_dev_fire && (wr_collect_left_q == '0))) else $fatal(1, "Extra device write");
            assert (!(host_wr_ack && wr_fifo_valid)) else $fatal(1, "Stale write data at new command");
`endif
            if (host_wr_ack) begin
                wr_active_q <= 1'b1;
                wr_addr_q <= host_wr_haddr;
                wr_collect_left_q <= {1'b0, host_wr_len} + (LEN_W+1)'(1);
                wr_commit_left_q <= {1'b0, host_wr_len} + (LEN_W+1)'(1);
                wr_lane_q <= '0;
                wr_pack_q <= '0;
            end else begin
                if (wr_dev_fire) begin
                    wr_lane_q <= wr_lane_q + 1'b1;
                    if (wr_lane_q == 2'd3) begin
                        wr_pack_q <= '0;
                        wr_collect_left_q <= wr_collect_left_q - 1'b1;
                    end else
                        wr_pack_q <= wr_assembled;
                end
                if (wr_mem_fire) begin
                    wr_addr_q <= wr_addr_q + ADDR_W'(8);
                    wr_commit_left_q <= wr_commit_left_q - 1'b1;
                    if (wr_commit_left_q == (LEN_W+1)'(1)) begin
                        wr_active_q <= 1'b0;
                        host_wr_done <= 1'b1;
                    end
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        assert (ADDR_W >= 4) else $fatal(1, "ADDR_W must be >= 4");
        assert (LEN_W >= 1) else $fatal(1, "LEN_W must be positive");
    end
`endif
`ifdef FORMAL
`include "dmac_monitor.svh"
`endif
endmodule
