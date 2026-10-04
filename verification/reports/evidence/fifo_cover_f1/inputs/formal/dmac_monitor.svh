// Transaction oracle counts observed handshakes rather than DUT countdowns.
reg f_dmac_past = 0;
reg f_rd_busy, f_wr_busy, f_rd_done, f_wr_done;
reg [ADDR_W-1:0] f_rd_base, f_wr_base;
reg [LEN_W:0] f_rd_total, f_wr_total, f_rd_mem, f_wr_mem;
reg [LEN_W+2:0] f_rd_dev, f_wr_dev;
reg [63:0] f_pack;
reg [2:0] f_rd_commands, f_wr_commands;
wire [LEN_W+2:0] f_rd_limit = {f_rd_total,2'b00};
wire [LEN_W+2:0] f_wr_limit = {f_wr_total,2'b00};
wire [63:0] f_input_lane = {48'b0,dev_wr_data} << (16*f_wr_dev[1:0]);
wire [63:0] f_pack_next = f_pack | f_input_lane;
always @(posedge clk) f_dmac_past <= 1;
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        f_rd_busy<=0; f_wr_busy<=0; f_rd_done<=0; f_wr_done<=0;
        f_rd_base<=0; f_wr_base<=0; f_rd_total<=0; f_wr_total<=0;
        f_rd_mem<=0; f_wr_mem<=0; f_rd_dev<=0; f_wr_dev<=0;
        f_pack<=0; f_rd_commands<=0; f_wr_commands<=0;
    end else begin
        f_rd_done <= rd_dev_fire && (f_rd_dev + 1'b1 == f_rd_limit);
        f_wr_done <= wr_mem_fire && (f_wr_mem + 1'b1 == f_wr_total);
        if (host_rd_req && host_rd_ack) begin
            f_rd_busy<=1; f_rd_base<=host_rd_haddr;
            f_rd_total<={1'b0,host_rd_len}+1'b1; f_rd_mem<=0; f_rd_dev<=0;
            if (f_rd_commands != 7) f_rd_commands<=f_rd_commands+1'b1;
        end else begin
            if (rd_mem_fire) f_rd_mem<=f_rd_mem+1'b1;
            if (rd_dev_fire) begin
                f_rd_dev<=f_rd_dev+1'b1;
                if (f_rd_dev+1'b1==f_rd_limit) f_rd_busy<=0;
            end
        end
        if (host_wr_req && host_wr_ack) begin
            f_wr_busy<=1; f_wr_base<=host_wr_haddr;
            f_wr_total<={1'b0,host_wr_len}+1'b1; f_wr_mem<=0; f_wr_dev<=0; f_pack<=0;
            if (f_wr_commands != 7) f_wr_commands<=f_wr_commands+1'b1;
        end else begin
            if (wr_dev_fire) begin
                f_wr_dev<=f_wr_dev+1'b1;
                f_pack <= (f_wr_dev[1:0]==3) ? 64'b0 : f_pack_next;
            end
            if (wr_mem_fire) begin
                f_wr_mem<=f_wr_mem+1'b1;
                if (f_wr_mem+1'b1==f_wr_total) f_wr_busy<=0;
            end
        end
    end
end
always @(posedge clk) if (f_dmac_past && rst_n) begin
    if ($past(rst_n && mem_wr_valid && !mem_wr_ready)) begin
        A_CK_WR_STALL_VALID: assert (mem_wr_valid);
        A_CK_WR_STALL_ADDRESS: assert ($stable(mem_wr_addr));
        A_CK_WR_STALL_DATA: assert ($stable(mem_wr_data));
    end
    if ($past(rst_n && mem_rd_valid && !mem_rd_ready)) begin
        A_CK_RD_STALL_VALID: assert (mem_rd_valid);
        A_CK_RD_STALL_ADDRESS: assert ($stable(mem_rd_addr));
    end
    A_CK_RD_ACTIVE: assert (rd_active_q == f_rd_busy);
    A_CK_WR_ACTIVE: assert (wr_active_q == f_wr_busy);
    A_CK_RD_FETCH_LEFT: assert (rd_fetch_left_q == f_rd_total-f_rd_mem);
    A_CK_RD_DELIVER_LEFT: assert (rd_deliver_left_q == f_rd_total-(f_rd_dev >> 2));
    A_CK_WR_COLLECT_LEFT: assert (wr_collect_left_q == f_wr_total-(f_wr_dev >> 2));
    A_CK_WR_COMMIT_LEFT: assert (wr_commit_left_q == f_wr_total-f_wr_mem);
    A_CK_RD_LANE: assert (rd_lane_q == f_rd_dev[1:0]);
    A_CK_WR_LANE: assert (wr_lane_q == f_wr_dev[1:0]);
    A_CK_RD_QUOTA: assert (f_rd_mem <= f_rd_total && f_rd_dev <= f_rd_limit);
    A_CK_WR_QUOTA: assert (f_wr_mem <= f_wr_total && f_wr_dev <= f_wr_limit);
    A_CK_RD_OCCUPANCY: assert (f_rd_mem-(f_rd_dev >> 2) == f_rd_count);
    A_CK_WR_OCCUPANCY: assert ((f_wr_dev >> 2)-f_wr_mem == f_wr_count);
    A_CK_RD_NO_EXTRA: assert (!rd_mem_fire || f_rd_mem < f_rd_total);
    A_CK_RD_NO_EXTRA_DEV: assert (!rd_dev_fire || f_rd_dev < f_rd_limit);
    A_CK_WR_NO_EXTRA: assert (!wr_dev_fire || f_wr_dev < f_wr_limit);
    A_CK_WR_NO_EXTRA_MEM: assert (!wr_mem_fire || f_wr_mem < f_wr_total);
    A_CK_RD_ADDRESS: assert (mem_rd_addr == ADDR_W'(f_rd_base + (f_rd_mem << 3)));
    A_CK_WR_ADDRESS: assert (mem_wr_addr == ADDR_W'(f_wr_base + (f_wr_mem << 3)));
    A_CK_RD_DONE: assert (host_rd_done == f_rd_done);
    A_CK_WR_DONE: assert (host_wr_done == f_wr_done);
    A_CK_RD_ACK_ADMISSION: assert (host_rd_ack == (host_rd_req && !f_rd_busy && !f_rd_done));
    A_CK_WR_ACK_ADMISSION: assert (host_wr_ack == (host_wr_req && !f_wr_busy && !f_wr_done));
    A_CK_RD_IDLE_EMPTY: assert (f_rd_busy || (f_rd_count==0 && f_rd_dev[1:0]==0));
    A_CK_WR_IDLE_EMPTY: assert (f_wr_busy || (f_wr_count==0 && f_wr_dev[1:0]==0));
    A_CK_WR_PACK: assert (wr_pack_q == f_pack);
    A_CK_WR_PACK_UNUSED_ZERO: assert ((f_pack >> (16*f_wr_dev[1:0])) == 0);
    A_CK_WR_ASSEMBLY: assert (!wr_dev_fire || wr_assembled == f_pack_next);
    A_CK_RD_DATA: assert (!rd_dev_fire || dev_rd_data == ((f_rd_head >> (16*f_rd_dev[1:0])) & 64'hffff));
    A_CK_WR_DATA: assert (!wr_mem_fire || mem_wr_data == f_wr_head);
    A_CK_RD_COMPLETE_COUNTS: assert (!host_rd_done || (f_rd_mem==f_rd_total && f_rd_dev==f_rd_limit));
    A_CK_WR_COMPLETE_COUNTS: assert (!host_wr_done || (f_wr_mem==f_wr_total && f_wr_dev==f_wr_limit));
    A_CK_RD_HEAD_VALID: assert (rd_fifo_valid == (f_rd_count != 0));
    A_CK_WR_HEAD_VALID: assert (wr_fifo_valid == (f_wr_count != 0));
    C_CK_THREE_RD: cover (f_rd_commands>=3 && host_rd_done);
    C_CK_THREE_WR: cover (f_wr_commands>=3 && host_wr_done);
    C_CK_DUPLEX_DONE: cover (host_rd_done && host_wr_done);
    C_CK_READ_WRAP: cover (rd_mem_fire && mem_rd_addr > ({ADDR_W{1'b1}} - ADDR_W'(8)));
    C_CK_WRITE_WRAP: cover (wr_mem_fire && mem_wr_addr > ({ADDR_W{1'b1}} - ADDR_W'(8)));
    if (LEN_W <= 3) begin
        C_CK_MAXLEN_RD: cover (f_rd_total == {1'b1,{LEN_W{1'b0}}} && host_rd_done);
        C_CK_MAXLEN_WR: cover (f_wr_total == {1'b1,{LEN_W{1'b0}}} && host_wr_done);
    end else begin
        C_CK_HIGH_LEN_RD: cover (f_rd_total[LEN_W] && rd_mem_fire);
        C_CK_HIGH_LEN_WR: cover (f_wr_total[LEN_W] && wr_mem_fire);
    end
    C_CK_PENDING_RD: cover (f_rd_busy && host_rd_req && !host_rd_ack && dev_rd_ack);
    C_CK_PENDING_WR: cover (f_wr_busy && host_wr_req && !host_wr_ack && mem_wr_valid);
end
