module dmac_checker (
  input wire clk,
  input wire rst_n,
  input wire host_rd_req,
  input wire [31:0] host_rd_haddr,
  input wire [31:0] host_rd_len,
  input wire host_wr_req,
  input wire [31:0] host_wr_haddr,
  input wire [31:0] host_wr_len,
  input wire mem_rd_ready,
  input wire [63:0] mem_rd_data,
  input wire mem_wr_ready,
  input wire dev_rd_req,
  input wire dev_wr_req,
  input wire [15:0] dev_wr_data,
  input wire host_rd_ack,
  input wire host_rd_done,
  input wire host_wr_ack,
  input wire host_wr_done,
  input wire mem_rd_valid,
  input wire [31:0] mem_rd_addr,
  input wire mem_wr_valid,
  input wire [31:0] mem_wr_addr,
  input wire [63:0] mem_wr_data,
  input wire dev_rd_ack,
  input wire [15:0] dev_rd_data,
  input wire dev_wr_ack
);
reg uc_past_valid = 1'b0;
always @(posedge clk) uc_past_valid <= 1'b1;
always @(posedge clk) begin
  if (!uc_past_valid) M_CK_API_RESET_INITIAL: assume (!rst_n);
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && host_rd_req && !host_rd_ack)) M_CK_API_HOST_RD_WAIT: assume (host_rd_req && $stable(host_rd_haddr) && $stable(host_rd_len));
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && host_wr_req && !host_wr_ack)) M_CK_API_HOST_WR_WAIT: assume (host_wr_req && $stable(host_wr_haddr) && $stable(host_wr_len));
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && dev_rd_req && !dev_rd_ack)) M_CK_API_DEV_RD_WAIT: assume (dev_rd_req);
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && dev_wr_req && !dev_wr_ack)) M_CK_API_DEV_WR_WAIT_REQ: assume (dev_wr_req);
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && dev_wr_req && !dev_wr_ack)) M_CK_API_DEV_WR_WAIT_DATA: assume (dev_wr_req && $stable(dev_wr_data));
end
always @* begin
  if (1'b1) A_CK_HOST_RD_ACK_REQ: assert (!host_rd_ack || (host_rd_req && rst_n));
end
always @* begin
  G_A_CK_HOST_RD_ACK_REQ: cover ((1'b1) && (host_rd_ack));
end
always @* begin
  if (1'b1) A_CK_HOST_WR_ACK_REQ: assert (!host_wr_ack || (host_wr_req && rst_n));
end
always @* begin
  G_A_CK_HOST_WR_ACK_REQ: cover ((1'b1) && (host_wr_ack));
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && host_rd_req && host_rd_ack) && mem_rd_valid) A_CK_HOST_RD_LATCH_ADDRESS: assert (mem_rd_addr == $past(host_rd_haddr));
end
always @(posedge clk) begin
  G_A_CK_HOST_RD_LATCH_ADDRESS: cover ((uc_past_valid && rst_n && $past(rst_n && host_rd_req && host_rd_ack) && mem_rd_valid) && (uc_past_valid && rst_n && $past(rst_n && host_rd_req && host_rd_ack) && mem_rd_valid));
end
always @(posedge clk) begin
  if ($past(uc_past_valid, 4) && rst_n && $past(rst_n, 1) && $past(rst_n, 2) && $past(rst_n, 3) && $past(rst_n, 4) && $past(rst_n, 5) && $past(host_wr_req && host_wr_ack, 5) && $past(dev_wr_req && dev_wr_ack, 4) && $past(dev_wr_req && dev_wr_ack, 3) && $past(dev_wr_req && dev_wr_ack, 2) && $past(dev_wr_req && dev_wr_ack, 1) && mem_wr_valid) A_CK_HOST_WR_LATCH_ADDRESS: assert (mem_wr_addr == $past(host_wr_haddr, 5));
end
always @(posedge clk) begin
  G_A_CK_HOST_WR_LATCH_ADDRESS: cover (($past(uc_past_valid, 4) && rst_n && $past(rst_n, 1) && $past(rst_n, 2) && $past(rst_n, 3) && $past(rst_n, 4) && $past(rst_n, 5) && $past(host_wr_req && host_wr_ack, 5) && $past(dev_wr_req && dev_wr_ack, 4) && $past(dev_wr_req && dev_wr_ack, 3) && $past(dev_wr_req && dev_wr_ack, 2) && $past(dev_wr_req && dev_wr_ack, 1) && mem_wr_valid) && ($past(uc_past_valid, 4) && rst_n && $past(rst_n, 1) && $past(rst_n, 2) && $past(rst_n, 3) && $past(rst_n, 4) && $past(rst_n, 5) && $past(host_wr_req && host_wr_ack, 5) && $past(dev_wr_req && dev_wr_ack, 4) && $past(dev_wr_req && dev_wr_ack, 3) && $past(dev_wr_req && dev_wr_ack, 2) && $past(dev_wr_req && dev_wr_ack, 1) && mem_wr_valid));
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && host_rd_req && host_rd_ack)) A_CK_HOST_RD_NO_IMMEDIATE_REACK: assert (!host_rd_ack);
end
always @(posedge clk) begin
  G_A_CK_HOST_RD_NO_IMMEDIATE_REACK: cover ((uc_past_valid && rst_n && $past(rst_n && host_rd_req && host_rd_ack)) && (uc_past_valid && rst_n && $past(rst_n && host_rd_req && host_rd_ack)));
end
always @(posedge clk) begin
  if (uc_past_valid && rst_n && $past(rst_n && host_wr_req && host_wr_ack)) A_CK_HOST_WR_NO_IMMEDIATE_REACK: assert (!host_wr_ack);
end
always @(posedge clk) begin
  G_A_CK_HOST_WR_NO_IMMEDIATE_REACK: cover ((uc_past_valid && rst_n && $past(rst_n && host_wr_req && host_wr_ack)) && (uc_past_valid && rst_n && $past(rst_n && host_wr_req && host_wr_ack)));
end
always @* begin
  if (1'b1) A_CK_HOST_RD_DONE_NO_ACK: assert (!host_rd_done || !host_rd_ack);
end
always @* begin
  G_A_CK_HOST_RD_DONE_NO_ACK: cover ((1'b1) && (host_rd_done));
end
always @* begin
  if (1'b1) A_CK_HOST_WR_DONE_NO_ACK: assert (!host_wr_done || !host_wr_ack);
end
always @* begin
  G_A_CK_HOST_WR_DONE_NO_ACK: cover ((1'b1) && (host_wr_done));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_rd_req) && ($past(host_rd_done && host_rd_req))) A_CK_HOST_RD_PENDING_AFTER_DONE: assert (host_rd_ack && !host_rd_done);
end
always @(posedge clk) begin
  G_A_CK_HOST_RD_PENDING_AFTER_DONE: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_rd_req) && ($past(host_rd_done && host_rd_req))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_wr_req) && ($past(host_wr_done && host_wr_req))) A_CK_HOST_WR_PENDING_AFTER_DONE: assert (host_wr_ack && !host_wr_done);
end
always @(posedge clk) begin
  G_A_CK_HOST_WR_PENDING_AFTER_DONE: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_wr_req) && ($past(host_wr_done && host_wr_req))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) A_CK_READ_MEM_FIRST_AFTER_ACCEPT: assert (mem_rd_valid && mem_rd_addr == $past(host_rd_haddr));
end
always @(posedge clk) begin
  G_A_CK_READ_MEM_FIRST_AFTER_ACCEPT: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) && (1'b1));
end
always @* begin
  if (1'b1) A_CK_READ_DEV_ACK_REQ: assert (!dev_rd_ack || (dev_rd_req && rst_n));
end
always @* begin
  G_A_CK_READ_DEV_ACK_REQ: cover ((1'b1) && (dev_rd_ack));
end
always @* begin
  if (1'b1) A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ: assert (dev_rd_req || !dev_rd_ack);
end
always @* begin
  G_A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ: cover ((1'b1) && (!dev_rd_req));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2))) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,2)) && ($past(mem_rd_valid && mem_rd_ready)) && (dev_rd_req && dev_rd_ack)) A_CK_READ_DEV_FRAGMENT_HOLD: assert (dev_rd_data == ($past(mem_rd_data) & 64'hffff));
end
always @(posedge clk) begin
  G_A_CK_READ_DEV_FRAGMENT_HOLD: cover (((($past(uc_past_valid)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2))) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,2)) && ($past(mem_rd_valid && mem_rd_ready)) && (dev_rd_req && dev_rd_ack)) && (1'b1));
end
always @* begin
  if (1'b1) A_CK_WRITE_DEV_ACK_REQ: assert (!dev_wr_ack || (dev_wr_req && rst_n));
end
always @* begin
  G_A_CK_WRITE_DEV_ACK_REQ: cover ((1'b1) && (dev_wr_ack));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4))) A_CK_WRITE_MEM_VALID_AFTER_WORD: assert (mem_wr_valid);
end
always @(posedge clk) begin
  G_A_CK_WRITE_MEM_VALID_AFTER_WORD: cover (((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4))) && (1'b1));
end
always @* begin
  if (1'b1) A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ: assert (dev_wr_req || !dev_wr_ack);
end
always @* begin
  G_A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ: cover ((1'b1) && (!dev_wr_req));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN: assert (mem_wr_valid && $stable(mem_wr_addr) && $stable(mem_wr_data));
end
always @(posedge clk) begin
  G_A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) A_CK_ADDRESS_RD_FIRST: assert (mem_rd_addr == $past(host_rd_haddr));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_RD_FIRST: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4)) && (mem_wr_valid)) A_CK_ADDRESS_WR_FIRST: assert (mem_wr_addr == $past(host_wr_haddr,5));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_WR_FIRST: cover (((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4)) && (mem_wr_valid)) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && mem_rd_ready)) && (mem_rd_valid)) A_CK_ADDRESS_RD_STEP: assert (mem_rd_addr == ($past(mem_rd_addr) + 32'd8));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_RD_STEP: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && mem_rd_ready)) && (mem_rd_valid)) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && mem_wr_ready)) && (mem_wr_valid)) A_CK_ADDRESS_WR_STEP: assert (mem_wr_addr == ($past(mem_wr_addr) + 32'd8));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_WR_STEP: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && mem_wr_ready)) && (mem_wr_valid)) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && !mem_rd_ready))) A_CK_ADDRESS_RD_HOLD: assert ((mem_rd_valid) && ($stable(mem_rd_addr)));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_RD_HOLD: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && !mem_rd_ready))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) A_CK_ADDRESS_WR_HOLD: assert ((mem_wr_valid) && ($stable(mem_wr_addr)) && ($stable(mem_wr_data)));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_WR_HOLD: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) && (1'b1));
end
always @(posedge clk) begin
  if ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && mem_rd_ready)) && (mem_rd_valid)) && ($past(mem_rd_addr > 32'hfffffff7))) A_CK_ADDRESS_RD_WRAP: assert (mem_rd_addr == ($past(mem_rd_addr) + 32'd8));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_RD_WRAP: cover (((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && mem_rd_ready)) && (mem_rd_valid)) && ($past(mem_rd_addr > 32'hfffffff7))) && (1'b1));
end
always @(posedge clk) begin
  if ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && mem_wr_ready)) && (mem_wr_valid)) && ($past(mem_wr_addr > 32'hfffffff7))) A_CK_ADDRESS_WR_WRAP: assert (mem_wr_addr == ($past(mem_wr_addr) + 32'd8));
end
always @(posedge clk) begin
  G_A_CK_ADDRESS_WR_WRAP: cover (((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && mem_wr_ready)) && (mem_wr_valid)) && ($past(mem_wr_addr > 32'hfffffff7))) && (1'b1));
end
always @(posedge clk) begin
  if (uc_past_valid) A_CK_QUOTA_ENCODING_BOUNDARY: assert ((!((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_rd_req && host_rd_ack,6)) && ($past(host_rd_len == 0,6)) && ($past(mem_rd_valid && mem_rd_ready,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) || host_rd_done) && (!((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_rd_req && host_rd_ack,10)) && ($past(host_rd_len == 1,10)) && ($past(mem_rd_valid && mem_rd_ready,9)) && ($past(mem_rd_valid && mem_rd_ready,8)) && ($past(dev_rd_req && dev_rd_ack,8)) && ($past(dev_rd_req && dev_rd_ack,7)) && ($past(dev_rd_req && dev_rd_ack,6)) && ($past(dev_rd_req && dev_rd_ack,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) || host_rd_done) && (!((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_wr_req && host_wr_ack,6)) && ($past(host_wr_len == 0,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready))) || host_wr_done) && (!((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_wr_req && host_wr_ack,10)) && ($past(host_wr_len == 1,10)) && ($past(dev_wr_req && dev_wr_ack,9)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready,5)) && ($past(mem_wr_valid && mem_wr_ready))) || host_wr_done));
end
always @(posedge clk) begin
  G_A_CK_QUOTA_ENCODING_BOUNDARY: cover ((uc_past_valid) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_rd_req && host_rd_ack,6)) && ($past(host_rd_len == 0,6)) && ($past(mem_rd_valid && mem_rd_ready,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) A_CK_QUOTA_RD_ZERO: assert (host_rd_done);
end
always @(posedge clk) begin
  G_A_CK_QUOTA_RD_ZERO: cover (((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_rd_req && host_rd_ack,6)) && ($past(host_rd_len == 0,6)) && ($past(mem_rd_valid && mem_rd_ready,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_wr_req && host_wr_ack,6)) && ($past(host_wr_len == 0,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready))) A_CK_QUOTA_WR_ZERO: assert (host_wr_done);
end
always @(posedge clk) begin
  G_A_CK_QUOTA_WR_ZERO: cover (((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_wr_req && host_wr_ack,6)) && ($past(host_wr_len == 0,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready))) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_rd_req && host_rd_ack,10)) && ($past(host_rd_len == 1,10)) && ($past(mem_rd_valid && mem_rd_ready,9)) && ($past(mem_rd_valid && mem_rd_ready,8)) && ($past(dev_rd_req && dev_rd_ack,8)) && ($past(dev_rd_req && dev_rd_ack,7)) && ($past(dev_rd_req && dev_rd_ack,6)) && ($past(dev_rd_req && dev_rd_ack,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) A_CK_QUOTA_RD_LEN1: assert ((host_rd_done) && (!$past(host_rd_done,4)));
end
always @(posedge clk) begin
  G_A_CK_QUOTA_RD_LEN1: cover (((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_rd_req && host_rd_ack,10)) && ($past(host_rd_len == 1,10)) && ($past(mem_rd_valid && mem_rd_ready,9)) && ($past(mem_rd_valid && mem_rd_ready,8)) && ($past(dev_rd_req && dev_rd_ack,8)) && ($past(dev_rd_req && dev_rd_ack,7)) && ($past(dev_rd_req && dev_rd_ack,6)) && ($past(dev_rd_req && dev_rd_ack,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_wr_req && host_wr_ack,10)) && ($past(host_wr_len == 1,10)) && ($past(dev_wr_req && dev_wr_ack,9)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready,5)) && ($past(mem_wr_valid && mem_wr_ready))) A_CK_QUOTA_WR_LEN1: assert ((host_wr_done) && (!$past(host_wr_done,4)));
end
always @(posedge clk) begin
  G_A_CK_QUOTA_WR_LEN1: cover (((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_wr_req && host_wr_ack,10)) && ($past(host_wr_len == 1,10)) && ($past(dev_wr_req && dev_wr_ack,9)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready,5)) && ($past(mem_wr_valid && mem_wr_ready))) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2))) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,2)) && ($past(mem_rd_valid && mem_rd_ready)) && (dev_rd_req && dev_rd_ack)) A_CK_DATA_RD_LOW_FIRST: assert (dev_rd_data == ($past(mem_rd_data) & 64'hffff));
end
always @(posedge clk) begin
  G_A_CK_DATA_RD_LOW_FIRST: cover (((($past(uc_past_valid)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2))) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,2)) && ($past(mem_rd_valid && mem_rd_ready)) && (dev_rd_req && dev_rd_ack)) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_rd_req && host_rd_ack,5)) && ($past(host_rd_len == 0,5)) && ($past(mem_rd_valid && mem_rd_ready,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack)) && (dev_rd_req && dev_rd_ack)) A_CK_DATA_RD_FOUR_LANES: assert (($past(dev_rd_data,3) == (($past(mem_rd_data,4) >> 0) & 64'hffff)) && ($past(dev_rd_data,2) == (($past(mem_rd_data,4) >> 16) & 64'hffff)) && ($past(dev_rd_data) == (($past(mem_rd_data,4) >> 32) & 64'hffff)) && (dev_rd_data == (($past(mem_rd_data,4) >> 48) & 64'hffff)));
end
always @(posedge clk) begin
  G_A_CK_DATA_RD_FOUR_LANES: cover (((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_rd_req && host_rd_ack,5)) && ($past(host_rd_len == 0,5)) && ($past(mem_rd_valid && mem_rd_ready,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack)) && (dev_rd_req && dev_rd_ack)) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(host_wr_len == 0,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack)) && (mem_wr_valid)) A_CK_DATA_WR_FOUR_LANES: assert (mem_wr_data == {$past(dev_wr_data),$past(dev_wr_data,2),$past(dev_wr_data,3),$past(dev_wr_data,4)});
end
always @(posedge clk) begin
  G_A_CK_DATA_WR_FOUR_LANES: cover (((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(host_wr_len == 0,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack)) && (mem_wr_valid)) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,8)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9))) && ($past(host_rd_req && host_rd_ack,9)) && ($past(host_rd_len == 1,9)) && ($past(mem_rd_valid && mem_rd_ready,8)) && ($past(mem_rd_valid && mem_rd_ready,7)) && ($past(dev_rd_req && dev_rd_ack,7)) && ($past(dev_rd_req && dev_rd_ack,6)) && ($past(dev_rd_req && dev_rd_ack,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack)) && (dev_rd_req && dev_rd_ack)) A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER: assert (($past(dev_rd_data,7) == (($past(mem_rd_data,8) >> 0) & 64'hffff)) && ($past(dev_rd_data,6) == (($past(mem_rd_data,8) >> 16) & 64'hffff)) && ($past(dev_rd_data,5) == (($past(mem_rd_data,8) >> 32) & 64'hffff)) && ($past(dev_rd_data,4) == (($past(mem_rd_data,8) >> 48) & 64'hffff)) && ($past(dev_rd_data,3) == (($past(mem_rd_data,7) >> 0) & 64'hffff)) && ($past(dev_rd_data,2) == (($past(mem_rd_data,7) >> 16) & 64'hffff)) && ($past(dev_rd_data) == (($past(mem_rd_data,7) >> 32) & 64'hffff)) && (dev_rd_data == (($past(mem_rd_data,7) >> 48) & 64'hffff)));
end
always @(posedge clk) begin
  G_A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER: cover (((($past(uc_past_valid,8)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9))) && ($past(host_rd_req && host_rd_ack,9)) && ($past(host_rd_len == 1,9)) && ($past(mem_rd_valid && mem_rd_ready,8)) && ($past(mem_rd_valid && mem_rd_ready,7)) && ($past(dev_rd_req && dev_rd_ack,7)) && ($past(dev_rd_req && dev_rd_ack,6)) && ($past(dev_rd_req && dev_rd_ack,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack)) && (dev_rd_req && dev_rd_ack)) && (1'b1));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,8)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9))) && ($past(host_wr_req && host_wr_ack,9)) && ($past(host_wr_len == 1,9)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(mem_wr_valid && mem_wr_ready,4)) && (mem_wr_valid && mem_wr_ready)) A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER: assert ((mem_wr_data == {$past(dev_wr_data),$past(dev_wr_data,2),$past(dev_wr_data,3),$past(dev_wr_data,4)}) && ($past(mem_wr_data,4) == {$past(dev_wr_data,5),$past(dev_wr_data,6),$past(dev_wr_data,7),$past(dev_wr_data,8)}));
end
always @(posedge clk) begin
  G_A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER: cover (((($past(uc_past_valid,8)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9))) && ($past(host_wr_req && host_wr_ack,9)) && ($past(host_wr_len == 1,9)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(mem_wr_valid && mem_wr_ready,4)) && (mem_wr_valid && mem_wr_ready)) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && !mem_rd_ready))) A_CK_FLOW_RD_VALID_ADDRESS_HOLD: assert ((mem_rd_valid) && ($stable(mem_rd_addr)));
end
always @(posedge clk) begin
  G_A_CK_FLOW_RD_VALID_ADDRESS_HOLD: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && !mem_rd_ready))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD: assert ((mem_wr_valid) && ($stable(mem_wr_addr)) && ($stable(mem_wr_data)));
end
always @(posedge clk) begin
  G_A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) && (1'b1));
end
always @* begin
  if (1'b1) A_CK_FLOW_DEV_RD_ACK_GATED: assert ((dev_rd_req && rst_n) || !dev_rd_ack);
end
always @* begin
  G_A_CK_FLOW_DEV_RD_ACK_GATED: cover ((1'b1) && (!dev_rd_req || !rst_n));
end
always @* begin
  if (1'b1) A_CK_FLOW_DEV_WR_ACK_GATED: assert ((dev_wr_req && rst_n) || !dev_wr_ack);
end
always @* begin
  G_A_CK_FLOW_DEV_WR_ACK_GATED: cover ((1'b1) && (!dev_wr_req || !rst_n));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD: assert (mem_wr_valid && $stable(mem_wr_addr) && $stable(mem_wr_data));
end
always @(posedge clk) begin
  G_A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready))) && (1'b1));
end
always @* begin
  if (1'b1) A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK: assert ((dev_rd_req || !dev_rd_ack) && (dev_wr_req || !dev_wr_ack));
end
always @* begin
  G_A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK: cover ((1'b1) && (!dev_rd_req || !dev_wr_req));
end
always @* begin
  if (!rst_n) A_CK_RESET_HOST_SILENCE: assert (!host_rd_ack && !host_wr_ack && !host_rd_done && !host_wr_done);
end
always @* begin
  G_A_CK_RESET_HOST_SILENCE: cover ((!rst_n) && (!rst_n));
end
always @* begin
  if (!rst_n) A_CK_RESET_DATA_CHANNEL_SILENCE: assert (!mem_rd_valid && !mem_wr_valid && !dev_rd_ack && !dev_wr_ack);
end
always @* begin
  G_A_CK_RESET_DATA_CHANNEL_SILENCE: cover ((!rst_n) && (!rst_n));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (!rst_n) && ($past(rst_n && mem_rd_valid && !mem_rd_ready))) A_CK_RESET_INTERRUPT_RD_STALL: assert ((!mem_rd_valid) && (!host_rd_ack) && (!host_rd_done));
end
always @(posedge clk) begin
  G_A_CK_RESET_INTERRUPT_RD_STALL: cover (((uc_past_valid) && (!rst_n) && ($past(rst_n && mem_rd_valid && !mem_rd_ready))) && (1'b1));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (!rst_n) && ($past(rst_n && mem_wr_valid && !mem_wr_ready))) A_CK_RESET_INTERRUPT_WR_STALL: assert ((!mem_wr_valid) && (!host_wr_ack) && (!host_wr_done));
end
always @(posedge clk) begin
  G_A_CK_RESET_INTERRUPT_WR_STALL: cover (((uc_past_valid) && (!rst_n) && ($past(rst_n && mem_wr_valid && !mem_wr_ready))) && (1'b1));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (!rst_n) && ($past(rst_n && ((dev_rd_req && dev_rd_ack) || (dev_wr_req && dev_wr_ack))))) A_CK_RESET_INTERRUPT_DEVICE_PARTIAL: assert (!dev_rd_ack && !dev_wr_ack && !host_rd_done && !host_wr_done);
end
always @(posedge clk) begin
  G_A_CK_RESET_INTERRUPT_DEVICE_PARTIAL: cover (((uc_past_valid) && (!rst_n) && ($past(rst_n && ((dev_rd_req && dev_rd_ack) || (dev_wr_req && dev_wr_ack))))) && (1'b1));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (!rst_n || !$past(rst_n))) A_CK_RESET_RD_DONE_CLEAR: assert (!host_rd_done);
end
always @(posedge clk) begin
  G_A_CK_RESET_RD_DONE_CLEAR: cover (((uc_past_valid) && (!rst_n || !$past(rst_n))) && (1'b1));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (!rst_n || !$past(rst_n))) A_CK_RESET_WR_DONE_CLEAR: assert (!host_wr_done);
end
always @(posedge clk) begin
  G_A_CK_RESET_WR_DONE_CLEAR: cover (((uc_past_valid) && (!rst_n || !$past(rst_n))) && (1'b1));
end
always @(posedge clk) begin
  if ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) && ($past(uc_past_valid)) && (!$past(rst_n,2))) A_CK_RESET_RD_RESTART_ADDRESS: assert ((mem_rd_addr == $past(host_rd_haddr)) && (!host_rd_done));
end
always @(posedge clk) begin
  G_A_CK_RESET_RD_RESTART_ADDRESS: cover (((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) && ($past(uc_past_valid)) && (!$past(rst_n,2))) && (1'b1));
end
always @(posedge clk) begin
  if (((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4)) && (mem_wr_valid)) && ($past(uc_past_valid,5)) && (!$past(rst_n,6))) A_CK_RESET_WR_RESTART_ADDRESS: assert ((mem_wr_addr == $past(host_wr_haddr,5)) && (!host_wr_done));
end
always @(posedge clk) begin
  G_A_CK_RESET_WR_RESTART_ADDRESS: cover ((((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4)) && (mem_wr_valid)) && ($past(uc_past_valid,5)) && (!$past(rst_n,6))) && (1'b1));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (rst_n) && (!$past(rst_n)) && (host_rd_req && host_wr_req && !host_rd_done && !host_wr_done)) A_CK_CONCURRENT_ACCEPT_AFTER_RESET: assert (host_rd_ack && host_wr_ack);
end
always @(posedge clk) begin
  G_A_CK_CONCURRENT_ACCEPT_AFTER_RESET: cover (((uc_past_valid) && (rst_n) && (!$past(rst_n)) && (host_rd_req && host_wr_req && !host_rd_done && !host_wr_done)) && (1'b1));
end
always @(posedge clk) begin
  if (1'b1) C_CK_CONCURRENT_MEM_TRANSFER: cover (rst_n && mem_rd_valid && mem_rd_ready && mem_wr_valid && mem_wr_ready);
end
always @(posedge clk) begin
  if (1'b1) C_CK_CONCURRENT_DEVICE_TRANSFER: cover (rst_n && dev_rd_req && dev_rd_ack && dev_wr_req && dev_wr_ack);
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && !mem_rd_ready)) && (mem_wr_valid && mem_wr_ready)) A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE: assert (mem_rd_valid && $stable(mem_rd_addr));
end
always @(posedge clk) begin
  G_A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_rd_valid && !mem_rd_ready)) && (mem_wr_valid && mem_wr_ready)) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready)) && (mem_rd_valid && mem_rd_ready)) A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE: assert (mem_wr_valid && $stable(mem_wr_addr) && $stable(mem_wr_data));
end
always @(posedge clk) begin
  G_A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(mem_wr_valid && !mem_wr_ready)) && (mem_rd_valid && mem_rd_ready)) && (1'b1));
end
always @(posedge clk) begin
  if (uc_past_valid && host_rd_done && host_wr_done) A_CK_CONCURRENT_SIMULTANEOUS_DONE: assert ($past(rst_n && dev_rd_req && dev_rd_ack) && $past(rst_n && mem_wr_valid && mem_wr_ready));
end
always @(posedge clk) begin
  G_A_CK_CONCURRENT_SIMULTANEOUS_DONE: cover ((uc_past_valid && host_rd_done && host_wr_done) && (host_rd_done && host_wr_done));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_done))) A_CK_DONE_RD_ONE_CYCLE: assert (!host_rd_done);
end
always @(posedge clk) begin
  G_A_CK_DONE_RD_ONE_CYCLE: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_done))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_wr_done))) A_CK_DONE_WR_ONE_CYCLE: assert (!host_wr_done);
end
always @(posedge clk) begin
  G_A_CK_DONE_WR_ONE_CYCLE: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_wr_done))) && (1'b1));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (host_rd_done)) A_CK_DONE_RD_PREV_DEV_HANDSHAKE: assert ($past(dev_rd_req && dev_rd_ack && rst_n));
end
always @(posedge clk) begin
  G_A_CK_DONE_RD_PREV_DEV_HANDSHAKE: cover (((uc_past_valid) && (host_rd_done)) && (host_rd_done));
end
always @(posedge clk) begin
  if ((uc_past_valid) && (host_wr_done)) A_CK_DONE_WR_PREV_MEM_HANDSHAKE: assert ($past(mem_wr_valid && mem_wr_ready && rst_n));
end
always @(posedge clk) begin
  G_A_CK_DONE_WR_PREV_MEM_HANDSHAKE: cover (((uc_past_valid) && (host_wr_done)) && (host_wr_done));
end
always @* begin
  if (1'b1) A_CK_DONE_RD_NO_ACK: assert (!host_rd_done || !host_rd_ack);
end
always @* begin
  G_A_CK_DONE_RD_NO_ACK: cover ((1'b1) && (host_rd_done));
end
always @* begin
  if (1'b1) A_CK_DONE_WR_NO_ACK: assert (!host_wr_done || !host_wr_ack);
end
always @* begin
  G_A_CK_DONE_WR_NO_ACK: cover ((1'b1) && (host_wr_done));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_rd_req) && ($past(host_rd_done && host_rd_req))) A_CK_DONE_RD_NEXT_ACK: assert (host_rd_ack && !host_rd_done);
end
always @(posedge clk) begin
  G_A_CK_DONE_RD_NEXT_ACK: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_rd_req) && ($past(host_rd_done && host_rd_req))) && (1'b1));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_wr_req) && ($past(host_wr_done && host_wr_req))) A_CK_DONE_WR_NEXT_ACK: assert (host_wr_ack && !host_wr_done);
end
always @(posedge clk) begin
  G_A_CK_DONE_WR_NEXT_ACK: cover ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_wr_req) && ($past(host_wr_done && host_wr_req))) && (1'b1));
end
always @(posedge clk) begin
  if ((((uc_past_valid) && (rst_n) && ($past(rst_n))) && ($past(host_rd_req && host_rd_ack))) && ($past(host_rd_haddr[2:0] != 3'b0))) C_CK_COVER_RD_NONALIGNED: cover ((mem_rd_valid) && (mem_rd_addr == $past(host_rd_haddr)));
end
always @(posedge clk) begin
  if (((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_wr_req && host_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4)) && (mem_wr_valid)) && ($past(host_wr_haddr[2:0] != 3'b0,5))) C_CK_COVER_WR_NONALIGNED: cover ((mem_wr_valid) && (mem_wr_addr == $past(host_wr_haddr,5)));
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_rd_req && host_rd_ack,6)) && ($past(host_rd_len == 0,6)) && ($past(mem_rd_valid && mem_rd_ready,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) C_CK_COVER_RD_LEN0_COMPLETE: cover (host_rd_done);
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,5)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6))) && ($past(host_wr_req && host_wr_ack,6)) && ($past(host_wr_len == 0,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready))) C_CK_COVER_WR_LEN0_COMPLETE: cover (host_wr_done);
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_rd_req && host_rd_ack,10)) && ($past(host_rd_len == 1,10)) && ($past(mem_rd_valid && mem_rd_ready,9)) && ($past(mem_rd_valid && mem_rd_ready,8)) && ($past(dev_rd_req && dev_rd_ack,8)) && ($past(dev_rd_req && dev_rd_ack,7)) && ($past(dev_rd_req && dev_rd_ack,6)) && ($past(dev_rd_req && dev_rd_ack,5)) && ($past(dev_rd_req && dev_rd_ack,4)) && ($past(dev_rd_req && dev_rd_ack,3)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack))) C_CK_COVER_RD_LEN1: cover (host_rd_done);
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,9)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10))) && ($past(host_wr_req && host_wr_ack,10)) && ($past(host_wr_len == 1,10)) && ($past(dev_wr_req && dev_wr_ack,9)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(mem_wr_valid && mem_wr_ready,5)) && ($past(mem_wr_valid && mem_wr_ready))) C_CK_COVER_WR_LEN1: cover (host_wr_done);
end
always @(posedge clk) begin
  if ((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past(host_rd_req && host_rd_ack && host_rd_len > 1,5))) C_CK_COVER_RD_LONGER_PROGRESS: cover ((mem_rd_valid && mem_rd_ready) && ($past(mem_rd_valid && mem_rd_ready,3)) && ($past(mem_rd_valid && mem_rd_ready,4)) && ($past(dev_rd_req && dev_rd_ack)) && ($past(dev_rd_req && dev_rd_ack,2)) && ($past(dev_rd_req && dev_rd_ack,3)) && (dev_rd_req && dev_rd_ack));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_WR_LONGER_PROGRESS: cover ((($past(uc_past_valid,12)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10)) && ($past(rst_n,11)) && ($past(rst_n,12)) && ($past(rst_n,13))) && ($past(host_wr_req && host_wr_ack && host_wr_len > 1,13)) && ($past(dev_wr_req && dev_wr_ack)) && ($past(dev_wr_req && dev_wr_ack,2)) && ($past(dev_wr_req && dev_wr_ack,3)) && ($past(dev_wr_req && dev_wr_ack,4)) && ($past(dev_wr_req && dev_wr_ack,5)) && ($past(dev_wr_req && dev_wr_ack,6)) && ($past(dev_wr_req && dev_wr_ack,7)) && ($past(dev_wr_req && dev_wr_ack,8)) && ($past(dev_wr_req && dev_wr_ack,9)) && ($past(dev_wr_req && dev_wr_ack,10)) && ($past(dev_wr_req && dev_wr_ack,11)) && ($past(dev_wr_req && dev_wr_ack,12)) && ($past(mem_wr_valid && mem_wr_ready,8)) && ($past(mem_wr_valid && mem_wr_ready,4)) && (mem_wr_valid && mem_wr_ready));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_RD_THREE_COMMANDS: cover ((($past(uc_past_valid,19)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10)) && ($past(rst_n,11)) && ($past(rst_n,12)) && ($past(rst_n,13)) && ($past(rst_n,14)) && ($past(rst_n,15)) && ($past(rst_n,16)) && ($past(rst_n,17)) && ($past(rst_n,18)) && ($past(rst_n,19)) && ($past(rst_n,20))) && (host_rd_done) && ($past(host_rd_done,7)) && ($past(host_rd_done,14)) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,6)) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,13)) && ($past(host_rd_req && host_rd_ack && host_rd_len == 0,20)));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_WR_THREE_COMMANDS: cover ((($past(uc_past_valid,19)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5)) && ($past(rst_n,6)) && ($past(rst_n,7)) && ($past(rst_n,8)) && ($past(rst_n,9)) && ($past(rst_n,10)) && ($past(rst_n,11)) && ($past(rst_n,12)) && ($past(rst_n,13)) && ($past(rst_n,14)) && ($past(rst_n,15)) && ($past(rst_n,16)) && ($past(rst_n,17)) && ($past(rst_n,18)) && ($past(rst_n,19)) && ($past(rst_n,20))) && (host_wr_done) && ($past(host_wr_done,7)) && ($past(host_wr_done,14)) && ($past(host_wr_req && host_wr_ack && host_wr_len == 0,6)) && ($past(host_wr_req && host_wr_ack && host_wr_len == 0,13)) && ($past(host_wr_req && host_wr_ack && host_wr_len == 0,20)));
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_rd_req) && ($past(host_rd_done && host_rd_req))) C_CK_COVER_RD_PENDING_NEXT: cover (host_rd_ack);
end
always @(posedge clk) begin
  if (((uc_past_valid) && (rst_n) && ($past(rst_n))) && (host_wr_req) && ($past(host_wr_done && host_wr_req))) C_CK_COVER_WR_PENDING_NEXT: cover (host_wr_ack);
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_RESET_RD_STALL: cover (($past(uc_past_valid)) && (rst_n) && (!$past(rst_n)) && ($past(rst_n && mem_rd_valid && !mem_rd_ready,2)) && (host_rd_req && host_rd_ack));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_RESET_WR_STALL: cover (($past(uc_past_valid)) && (rst_n) && (!$past(rst_n)) && ($past(rst_n && mem_wr_valid && !mem_wr_ready,2)) && (host_wr_req && host_wr_ack));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_RESET_PARTIAL_FRAGMENT: cover (($past(uc_past_valid)) && (rst_n) && (!$past(rst_n)) && ($past(rst_n && ((dev_rd_req && dev_rd_ack) || (dev_wr_req && dev_wr_ack)),2)) && ((host_rd_req && host_rd_ack) || (host_wr_req && host_wr_ack)));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_DUPLEX_OVERLAP: cover ((($past(uc_past_valid,4)) && (rst_n) && ($past(rst_n)) && ($past(rst_n,2)) && ($past(rst_n,3)) && ($past(rst_n,4)) && ($past(rst_n,5))) && ($past((host_rd_req && host_rd_ack) && (host_wr_req && host_wr_ack),5)) && (mem_rd_valid && mem_rd_ready) && (dev_wr_req && dev_wr_ack));
end
always @(posedge clk) begin
  if (1'b1) C_CK_COVER_SIMULTANEOUS_DONE: cover (rst_n && host_rd_done && host_wr_done);
end
endmodule
